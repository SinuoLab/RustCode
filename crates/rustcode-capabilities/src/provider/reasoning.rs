//! `reasoning_content` round-trip POLICY for OpenAI-compatible providers.
//!
//! The kernel STORES reasoning losslessly on `Message.reasoning`; THIS module decides
//! the per-model *wire* behaviour -- whether the prior turn's reasoning is echoed back
//! on the next request. (Mechanism lives in L0; policy lives here in L1.)
//!
//! Why per-model: OpenAI-compatible "reasoning models" disagree on the round-trip.
//!
//! ```text
//! deepseek-v4*           REQUIRES reasoning_content echoed on assistant tool-call
//!                        turns (HTTP 400 "must be passed back" otherwise); an empty
//!                        string is rejected, so a non-empty REASONING_PLACEHOLDER is
//!                        sent when no reasoning was captured.
//! deepseek-r1/reasoner   FORBIDS echoing reasoning_content (HTTP 400 if sent).
//! GLM / everything else  safe default: do not echo (GLM does not error either way;
//!                        omitting keeps requests minimal).
//! ```
//!
//! There is NO opaque signature on this path -- reasoning is plain text -- so the flat
//! kernel `reasoning: Option<String>` is fully sufficient (see its FUTURE doc note for
//! the signed-provider extension).

/// Placeholder echoed when a model REQUIRES `reasoning_content` on a historical
/// assistant message but none was captured (resumed/compacted history, or a turn
/// produced by a non-thinking model). DeepSeek-V4 rejects an *empty* `reasoning_content`
/// on tool-call messages, so a non-empty placeholder is mandatory under [`ReasoningPolicy::Include`].
///
/// It is a single NON-PROSE sentinel (`.`), not an English sentence: at high context a
/// history full of an English placeholder *sentence* led DeepSeek-V4-Flash to MIMIC it and
/// emit it as its only assistant text, stalling the turn. A bare middle-dot satisfies the
/// non-empty requirement without giving the model prose to echo (ported from core 54c9e4bb).
pub const REASONING_PLACEHOLDER: &str = ".";

/// The wire FIELD NAME a provider uses to carry its reasoning / chain-of-thought.
///
/// Upstream OpenAI-compatible vendors disagree on the spelling: most (DeepSeek-V4,
/// GLM, ...) stream `reasoning_content`, but some (certain Qwen / vLLM / gateway
/// builds) use the shorter `reasoning`. Under [`ReasoningPolicy::Preserve`] the
/// adapter echoes the prior turn's reasoning back on the SAME field it streamed on,
/// so both namings round-trip without a hard-coded guess. Everywhere else the field
/// is fixed to [`ReasoningField::ReasoningContent`].
#[derive(Clone, Copy, Debug, PartialEq, Eq, Default)]
pub enum ReasoningField {
    /// `reasoning_content` -- the common OpenAI-compatible field (the default).
    #[default]
    ReasoningContent,
    /// `reasoning` -- the shorter spelling some upstreams stream.
    Reasoning,
}

impl ReasoningField {
    /// The exact JSON key this field serialises to on the wire.
    pub fn key(&self) -> &'static str {
        match self {
            ReasoningField::ReasoningContent => "reasoning_content",
            ReasoningField::Reasoning => "reasoning",
        }
    }

    /// Dense encoding for the lock-free [`HeardReasoningField`] cell.
    const fn as_u8(self) -> u8 {
        match self {
            ReasoningField::ReasoningContent => 0,
            ReasoningField::Reasoning => 1,
        }
    }

    /// Inverse of [`ReasoningField::as_u8`]; anything unexpected decodes to the
    /// default `reasoning_content` so a corrupt cell can only ever pick the safe
    /// field, never an invalid one.
    fn from_u8(v: u8) -> ReasoningField {
        match v {
            1 => ReasoningField::Reasoning,
            _ => ReasoningField::ReasoningContent,
        }
    }
}

/// A cloneable, lock-free cell that REMEMBERS which reasoning field name a provider
/// streamed on this session, so the NEXT request can echo reasoning back on the same
/// field under [`ReasoningPolicy::Preserve`].
///
/// `Arc`-shared: the streaming decoder records the field as deltas arrive, and
/// [`build_request`](super::openai_compat) reads it back on the next turn -- both hold
/// one clone of the SAME cell, so a turn that streamed `reasoning` keeps echoing
/// `reasoning` for the rest of the session. Relaxed ordering suffices: this is a
/// single-word hint that only needs to become visible, never a synchronisation point.
/// `Default` = [`ReasoningField::ReasoningContent`] so a provider that never streams
/// reasoning still echoes the common field.
#[derive(Clone, Default)]
pub struct HeardReasoningField(std::sync::Arc<HeardReasoningFieldInner>);

#[derive(Default)]
struct HeardReasoningFieldInner {
    // 0 == ReasoningContent (AtomicU8's Default), 1 == Reasoning; see
    // ReasoningField::{as_u8, from_u8}. The Default-on-zero invariant is what makes
    // HeardReasoningField::default() decode to ReasoningContent.
    field: std::sync::atomic::AtomicU8,
}

impl HeardReasoningField {
    /// The field name last heard (Relaxed load). Defaults to `reasoning_content`.
    pub fn get(&self) -> ReasoningField {
        ReasoningField::from_u8(self.0.field.load(std::sync::atomic::Ordering::Relaxed))
    }

    /// Record the field name heard on the wire (Relaxed store).
    pub fn set(&self, field: ReasoningField) {
        self.0
            .field
            .store(field.as_u8(), std::sync::atomic::Ordering::Relaxed);
    }
}

/// Whether a model echoes prior-turn `reasoning_content` back on the next request.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ReasoningPolicy {
    /// Echo `reasoning_content` on assistant messages (placeholder if missing).
    Include,
    /// Never echo `reasoning_content`.
    Exclude,
    /// Echo on WHICHEVER field the provider streamed reasoning on this session
    /// (`reasoning_content` or `reasoning`, see [`HeardReasoningField`]); the usual
    /// `REASONING_PLACEHOLDER` applies when no reasoning was captured. Byte-identical
    /// to [`ReasoningPolicy::Include`] for a `reasoning_content`-streaming provider.
    Preserve,
}

impl ReasoningPolicy {
    /// Parse the user-facing `reasoning_history` config value into an explicit
    /// override. `None`/empty ⇒ `Ok(None)` (caller falls back to [`derive`]);
    /// `"include"`/`"exclude"`/`"preserve"` (case/space-insensitive) ⇒ the matching
    /// policy; any other value is a typo and fails fast -- mirrors `rustcode-core`'s
    /// load-time validation so a bad config errors the same way on either engine.
    ///
    /// [`derive`]: ReasoningPolicy::derive
    pub fn from_config(value: Option<&str>) -> Result<Option<Self>, String> {
        match value.map(|s| s.trim().to_ascii_lowercase()) {
            None => Ok(None),
            Some(s) if s.is_empty() => Ok(None),
            Some(s) if s == "include" => Ok(Some(ReasoningPolicy::Include)),
            Some(s) if s == "exclude" => Ok(Some(ReasoningPolicy::Exclude)),
            Some(s) if s == "preserve" => Ok(Some(ReasoningPolicy::Preserve)),
            Some(other) => Err(format!(
                "invalid `reasoning_history` value {other:?} -- expected \"include\", \
                 \"exclude\", or \"preserve\" (unset = auto-detect)"
            )),
        }
    }

    /// Derive the default policy from the model name + base URL (some vendors are only
    /// identifiable by host, e.g. Moonshot/MiMo gateways). An explicit
    /// [`OpenAiCompatConfig::reasoning_policy`](super::OpenAiCompatConfig) override takes
    /// precedence over this. Faithfully ports `rustcode-core`'s `derive_reasoning_policy`.
    pub fn derive(model: &str, base_url: &str) -> Self {
        let m = model.to_ascii_lowercase();
        let u = base_url.to_ascii_lowercase();
        if m.contains("deepseek-reasoner") || m.contains("deepseek-r1") {
            // DeepSeek V3 family: rejects echoed reasoning_content (400).
            ReasoningPolicy::Exclude
        } else if m.contains("deepseek-v4") {
            // DeepSeek V4 thinking mode: REQUIRES reasoning_content on tool-call turns.
            ReasoningPolicy::Include
        } else if m.starts_with("kimi-")
            || m.starts_with("moonshot")
            || m.starts_with("mimo-")
            || u.contains("moonshot")
            || u.contains("kimi")
            || u.contains("xiaomimimo")
            || u.contains("mimo")
        {
            // Moonshot/Kimi/MiMo: require reasoning_content on every assistant tool_call.
            ReasoningPolicy::Include
        } else {
            // GLM and normal OpenAI models: safe default -- nothing to echo.
            ReasoningPolicy::Exclude
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn deepseek_v4_includes() {
        assert_eq!(
            ReasoningPolicy::derive("deepseek-v4-flash", ""),
            ReasoningPolicy::Include
        );
        assert_eq!(
            ReasoningPolicy::derive("DeepSeek-V4", ""),
            ReasoningPolicy::Include
        );
    }

    #[test]
    fn deepseek_r1_excludes() {
        assert_eq!(
            ReasoningPolicy::derive("deepseek-r1", ""),
            ReasoningPolicy::Exclude
        );
        assert_eq!(
            ReasoningPolicy::derive("deepseek-reasoner", ""),
            ReasoningPolicy::Exclude
        );
        // r1 wins even if the URL looks like a moonshot host.
        assert_eq!(
            ReasoningPolicy::derive("deepseek-r1", "https://api.moonshot.cn/v1"),
            ReasoningPolicy::Exclude
        );
    }

    #[test]
    fn moonshot_kimi_mimo_include() {
        assert_eq!(
            ReasoningPolicy::derive("kimi-k2", ""),
            ReasoningPolicy::Include
        );
        assert_eq!(
            ReasoningPolicy::derive("moonshot-v1-8k", ""),
            ReasoningPolicy::Include
        );
        // MiMo by MODEL NAME (reuses DeepSeek-V4 thinking protocol) -- even on a generic
        // gateway URL that doesn't contain "mimo".
        assert_eq!(
            ReasoningPolicy::derive("mimo-v2.5-pro", "https://generic-gateway.example/v1"),
            ReasoningPolicy::Include
        );
        // identifiable only by host:
        assert_eq!(
            ReasoningPolicy::derive("some-model", "https://api.moonshot.cn/v1"),
            ReasoningPolicy::Include
        );
        assert_eq!(
            ReasoningPolicy::derive("some-model", "https://api-inference.xiaomimimo.com/v1"),
            ReasoningPolicy::Include
        );
    }

    #[test]
    fn from_config_parses_override_or_errors() {
        assert_eq!(ReasoningPolicy::from_config(None), Ok(None));
        assert_eq!(ReasoningPolicy::from_config(Some("")), Ok(None));
        assert_eq!(ReasoningPolicy::from_config(Some("  ")), Ok(None));
        assert_eq!(
            ReasoningPolicy::from_config(Some("include")),
            Ok(Some(ReasoningPolicy::Include))
        );
        assert_eq!(
            ReasoningPolicy::from_config(Some(" Exclude ")),
            Ok(Some(ReasoningPolicy::Exclude))
        );
        assert_eq!(
            ReasoningPolicy::from_config(Some("Preserve")),
            Ok(Some(ReasoningPolicy::Preserve))
        );
        assert!(ReasoningPolicy::from_config(Some("sometimes")).is_err());
    }

    #[test]
    fn reasoning_field_key_maps_to_wire_spelling() {
        assert_eq!(ReasoningField::ReasoningContent.key(), "reasoning_content");
        assert_eq!(ReasoningField::Reasoning.key(), "reasoning");
    }

    #[test]
    fn heard_reasoning_field_defaults_to_reasoning_content() {
        // The Default-on-zero invariant: a provider that never streams reasoning
        // must still echo the common `reasoning_content` field under Preserve.
        let heard = HeardReasoningField::default();
        assert_eq!(heard.get(), ReasoningField::ReasoningContent);
    }

    #[test]
    fn heard_reasoning_field_set_get_roundtrips() {
        let heard = HeardReasoningField::default();
        heard.set(ReasoningField::Reasoning);
        assert_eq!(heard.get(), ReasoningField::Reasoning);
        heard.set(ReasoningField::ReasoningContent);
        assert_eq!(heard.get(), ReasoningField::ReasoningContent);
        // Clone is an Arc clone: both handles observe the SAME cell.
        let clone = heard.clone();
        heard.set(ReasoningField::Reasoning);
        assert_eq!(clone.get(), ReasoningField::Reasoning);
    }

    #[test]
    fn glm_and_default_exclude() {
        assert_eq!(
            ReasoningPolicy::derive("glm-5.1", "https://open.bigmodel.cn/api/paas/v4"),
            ReasoningPolicy::Exclude
        );
        assert_eq!(
            ReasoningPolicy::derive("gpt-4o", "https://api.openai.com/v1"),
            ReasoningPolicy::Exclude
        );
        assert_eq!(ReasoningPolicy::derive("", ""), ReasoningPolicy::Exclude);
    }
}
