use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ProviderConfig {
    #[serde(rename = "type")]
    pub provider_type: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub api_key: Option<String>,
    pub model: String,
    pub base_url: Option<String>,
    /// Arbitrary extra HTTP headers sent on every request to this provider.
    /// Useful for self-hosted gateways that require custom auth/tenant headers.
    /// Values are sourced from config only -- never hardcoded.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub extra_headers: Option<std::collections::HashMap<String, String>>,
    /// Optional forward proxy (e.g. `http://corp-proxy:3128`) applied to this
    /// provider's HTTP client. Respects `skip_tls_verify`.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub proxy: Option<String>,
    pub system_prompt: Option<String>,
    /// Explicit image-input capability override. `None` keeps automatic model-name
    /// detection; `Some(true/false)` is authoritative for custom model ids and
    /// compatibility gateways whose wire name does not advertise its modalities.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub supports_vision: Option<bool>,
    /// Override User-Agent for this provider (useful when the upstream blocks generic UAs).
    /// Defaults to `rustcode/<version>` if not set.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub user_agent: Option<String>,
    /// Maximum tokens to use for context (system prompt + messages).
    /// The windowing algorithm fits messages within this budget,
    /// condensing old tool results to save space.
    /// Defaults vary by provider type; use `default_context_window_for` after deserialization.
    #[serde(default = "default_context_window")]
    pub context_window: usize,
    /// Maximum tokens the model can output per response.
    /// Larger values allow batching multiple write_file calls in one turn.
    /// If not set, defaults to context_window / 4.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub max_tokens: Option<usize>,
    /// Kimi K2.5 / K2.6 thinking control -- emitted as `thinking.type`
    /// in the request body. `"enabled"` | `"disabled"`. K2-thinking is
    /// always on and ignores this. Unset = don't forward the field.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub thinking_type: Option<String>,
    /// Kimi K2.6 Preserved Thinking -- emitted as `thinking.keep` in the
    /// request body. `"all"` to have the server reprocess historical
    /// reasoning_content (more expensive). Unset = default behavior.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub thinking_keep: Option<String>,
    /// Override the history-echo policy for `reasoning_content` on
    /// historical assistant tool_call messages. `"include"` = always echo
    /// the stored reasoning back (required by Moonshot Kimi K2 thinking,
    /// DeepSeek V4 thinking mode); `"exclude"` = never echo (required by
    /// DeepSeek V3 R1, safe default for plain OpenAI); `"preserve"` = echo
    /// on whichever field the upstream STREAMED reasoning on this session
    /// (`reasoning_content` or the shorter `reasoning`). Unset = use the
    /// built-in auto-detect heuristic based on model name / base_url.
    /// Lets users work around new provider quirks without a code change.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub reasoning_history: Option<String>,
    /// Reasoning effort control. `"auto"` declares that this concrete endpoint
    /// supports effort switching while leaving the API default in effect;
    /// `"low" | "medium" | "high" | "xhigh" | "max"` also set the model default.
    /// Sent as top-level `reasoning_effort` in the request body.
    /// None = endpoint capability is unknown/disabled; don't send the field.
    /// For OpenAI-compatible endpoints, a configured value explicitly enables
    /// the field for this model profile; unconfigured custom endpoints omit it.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub reasoning_effort: Option<String>,
    /// Optional per-endpoint restriction of which reasoning-effort LEVELS this
    /// model exposes (a subset of `["low","medium","high","xhigh","max"]`). `None`/empty
    /// ⇒ all levels. See [`super::allowed_effort_levels`]. Constrains only what the
    /// UI offers and what `/effort` accepts; the wire still sends a single value.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub reasoning_effort_levels: Option<Vec<String>>,
    /// Whether extended thinking is enabled for this provider.
    /// For Claude: sends `thinking.type = "enabled"` in request body.
    /// Default: not set (thinking disabled).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub thinking_enabled: Option<bool>,
    /// Maximum tokens allocated to the thinking phase.
    /// Claude: sent as `thinking.budget_tokens`.
    /// Default: 10000 when thinking is enabled.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub thinking_budget: Option<u32>,
    /// Skip TLS certificate verification for this provider.
    /// Useful for self-signed certificates in enterprise/internal environments.
    /// Default: false (TLS verification enabled).
    /// WARNING: Setting this to true reduces security by accepting any certificate.
    #[serde(default, skip_serializing_if = "std::ops::Not::not")]
    pub skip_tls_verify: bool,
    /// If true, this provider was added at runtime (e.g. OAuth /login)
    /// and should NOT be persisted to config.toml on save.
    #[serde(skip)]
    pub ephemeral: bool,
    /// Capability rank for the `task` subagent's strong/weak auto-routing. Higher = more
    /// capable. A provider WITHOUT this set does NOT participate in tier routing. Populated
    /// from the managed platform's model list at login (or hand-written in config.toml). When
    /// ≥2 providers carry it, the highest is the `capable` tier and the lowest the `fast`
    /// tier; fewer than 2 (or a non-participating host) ⇒ the subagent uses the current model.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub capable_model: Option<i64>,
    /// Max attempts (including the first request) for provider OPEN retries;
    /// when set, also caps kernel-owned HTTP 429 recovery. `None` preserves
    /// each layer's default. Set `1` to disable adapter-level and 429 retries.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub retry_max_attempts: Option<u32>,
    /// Maps a requested model alias to the wire model name. Resolved once at the
    /// provider factory; adapters never see aliases. Empty ⇒ identity mapping.
    #[serde(default, skip_serializing_if = "ModelMapping::is_empty")]
    pub model_mapping: ModelMapping,
    /// Per-provider HTTP timeouts. `None` keeps every adapter default, which is
    /// what every config written before this field existed gets.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub timeout: Option<ProviderTimeout>,
}

/// HTTP-level timeouts for one provider, in SECONDS. Every field is optional and
/// falls back to the adapter's own default when unset, so an existing
/// `config.toml` keeps its current behaviour byte for byte.
///
/// The three budgets are deliberately distinct:
///
/// - `connect` -- TCP + TLS handshake up to the first response byte. Guards a
///   dead gateway / blackholed proxy. Maps to each adapter's `connect_timeout`.
/// - `request` -- the whole OPEN phase (send request -> response headers). Maps to
///   `open_timeout`. **OpenAI-compatible and Anthropic only**: the Ollama adapter
///   has no such seam, so the field is ignored there rather than emulated.
/// - `idle` -- max byte-idle gap INSIDE a stream (and the first-token wait).
///   Maps to `idle_timeout`, i.e. the runtime's `stream_timeout`.
///
/// `deny_unknown_fields` is intentional: a typo like `timeout = 30` (a bare
/// integer, or a misspelled key) must be rejected at load time instead of being
/// silently ignored and leaving the user with a timeout they did not set.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ProviderTimeout {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub connect: Option<u64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub request: Option<u64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub idle: Option<u64>,
}

impl ProviderTimeout {
    /// True when no budget is set, so the field is omitted from serialized
    /// config output.
    pub fn is_empty(&self) -> bool {
        self.connect.is_none() && self.request.is_none() && self.idle.is_none()
    }

    pub fn connect(&self) -> Option<std::time::Duration> {
        self.connect.map(std::time::Duration::from_secs)
    }

    pub fn request(&self) -> Option<std::time::Duration> {
        self.request.map(std::time::Duration::from_secs)
    }

    pub fn idle(&self) -> Option<std::time::Duration> {
        self.idle.map(std::time::Duration::from_secs)
    }
}

/// A provider *account*: a reusable connection + credential identity (new schema,
/// design §3.2). `provider` references a preset id (see
/// [`super::provider_preset`]) or a custom-compatible preset. One account can
/// back many [`ModelProfileConfig`]s, so two models from the same vendor no
/// longer duplicate `type` / `base_url` / `api_key`.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ProviderAccountConfig {
    /// Preset id or custom protocol preset (`openai-compatible` /
    /// `anthropic-compatible`).
    pub provider: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub display_name: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub api_key: Option<String>,
    /// Overrides the preset's default base URL. Required for custom-compatible
    /// providers (which have no preset default).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub base_url: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub extra_headers: Option<std::collections::HashMap<String, String>>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub proxy: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub user_agent: Option<String>,
    #[serde(default, skip_serializing_if = "std::ops::Not::not")]
    pub skip_tls_verify: bool,
    /// Enterprise/self-hosted control-plane URL for OAuth-style providers
    /// (reserved; unused until an OAuth adapter lands).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub enterprise_url: Option<String>,
    /// Runtime-only account (e.g. OAuth `/login`); never persisted to disk.
    #[serde(skip)]
    pub ephemeral: bool,
}

/// A model *profile*: a selectable model plus its model-specific behavior (new
/// schema, design §3.3). `account` references a [`ProviderAccountConfig`]; the
/// profile owns only per-model limits, so an account can expose several models.
/// The recommended selection-id key is `<account>/<model-or-alias>`.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ModelProfileConfig {
    pub account: String,
    /// Wire model name sent to the provider (kept separate from the selection id
    /// so aliases / deployment names are supported).
    pub model: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub display_name: Option<String>,
    /// Optional per-model system-prompt override (carried through resolution,
    /// design §14.5). Projected from a legacy provider's `system_prompt`.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub system_prompt: Option<String>,
    /// Explicit image-input capability override. `None` means Auto.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub supports_vision: Option<bool>,
    #[serde(default = "default_context_window")]
    pub context_window: usize,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub max_tokens: Option<usize>,
    /// Per-model capability rank for the `task` subagent's strong/weak routing
    /// (design §14.2). Higher = more capable; unset ⇒ does not participate.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub capable_model: Option<i64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub thinking_type: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub thinking_keep: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub reasoning_history: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub reasoning_effort: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub reasoning_effort_levels: Option<Vec<String>>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub thinking_enabled: Option<bool>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub thinking_budget: Option<u32>,
    /// Max attempts (including the first request) for provider OPEN retries;
    /// when set, also caps kernel-owned HTTP 429 recovery. `None` preserves
    /// each layer's default.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub retry_max_attempts: Option<u32>,
    /// Per-profile model alias table (see [`ModelMapping`]). Inherited from the
    /// backing account at resolution time when absent here.
    #[serde(default, skip_serializing_if = "ModelMapping::is_empty")]
    pub model_mapping: ModelMapping,
    /// Ordered fallback chain of model selection ids. When this model fails in a
    /// way that another model could survive (rate limit, upstream 5xx, timeout,
    /// auth), the runtime walks the chain and continues the same turn on the
    /// first target that works. Empty (the default) means "no fallback" -- the
    /// turn fails exactly as it does today.
    ///
    /// Order is meaningful: `["a", "b"]` tries `a` before `b`. Entries must be
    /// resolvable selection ids in the same config, must not name this model,
    /// and the chain is bounded by [`MAX_MODEL_FALLBACK_CHAIN`]. Validated by
    /// [`super::Config::validate_model_fallback_chains`]; see
    /// `docs/model-fallback-requirements.md` FR-1.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub fallback: Vec<String>,
    /// Unix seconds when this profile was added; drives newest-first ordering
    /// so a freshly added custom model appears at the top of `/model` and the
    /// provider panel instead of being buried in alphabetical order. Missing on
    /// profiles written before this field existed (they deserialize to 0) and
    /// therefore sink beneath everything added later, which is the desired
    /// migration behavior. A rename/re-save keeps the stored value untouched.
    #[serde(default)]
    pub added_at: i64,
}

/// One flattened, immutable resolution of a model selection (design §3.4). This
/// is the single value provider construction consumes -- accounts, presets,
/// legacy entries, and environment variables are all resolved away by
/// [`super::Config::resolve_model`]. Carries everything a provider adapter needs
/// (including the per-model dynamic `base_url` and `system_prompt`, §14.5) but
/// owns no runtime state. Never serialized; `Debug` redacts the api key.
#[derive(Clone)]
pub struct ResolvedModelConfig {
    pub selection_id: String,
    pub account_id: String,
    /// Preset id (or custom protocol id) the account referenced.
    pub provider_id: String,
    /// Wire protocol string the provider factory dispatches on.
    pub provider_type: String,
    pub base_url: Option<String>,
    pub api_key: Option<String>,
    /// Arbitrary extra HTTP headers for the resolved provider (self-hosted
    /// gateway auth/tenant). Sourced from config only.
    pub extra_headers: Option<std::collections::HashMap<String, String>>,
    /// Per-provider forward proxy override.
    pub proxy: Option<String>,
    pub model: String,
    /// Final capability after applying the profile override and Auto fallback.
    pub supports_vision: bool,
    pub context_window: usize,
    pub max_tokens: Option<usize>,
    pub system_prompt: Option<String>,
    pub user_agent: Option<String>,
    pub skip_tls_verify: bool,
    pub thinking_type: Option<String>,
    pub thinking_keep: Option<String>,
    pub reasoning_history: Option<String>,
    pub reasoning_effort: Option<String>,
    pub reasoning_effort_levels: Option<Vec<String>>,
    pub thinking_enabled: Option<bool>,
    pub thinking_budget: Option<u32>,
    pub capable_model: Option<i64>,
    /// Resolved model alias table (see [`ModelMapping`]); identity when empty.
    pub model_mapping: ModelMapping,
    /// Max attempts (including the first request) for provider OPEN retries;
    /// when set, also caps kernel-owned HTTP 429 recovery. `None` preserves
    /// each layer's default.
    pub retry_max_attempts: Option<u32>,
}

impl std::fmt::Debug for ResolvedModelConfig {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("ResolvedModelConfig")
            .field("selection_id", &self.selection_id)
            .field("account_id", &self.account_id)
            .field("provider_id", &self.provider_id)
            .field("provider_type", &self.provider_type)
            .field("base_url", &self.base_url)
            .field("api_key", &self.api_key.as_ref().map(|_| "<redacted>"))
            .field("model", &self.model)
            .field("context_window", &self.context_window)
            .finish_non_exhaustive()
    }
}

impl ResolvedModelConfig {
    /// Reconstruct a legacy-shaped [`ProviderConfig`] from this resolution.
    /// Lets consumers that still key off `config.providers` (the daemon live
    /// runtime, the TUI `/think`/`/effort` readers) accept a new-schema or
    /// projected legacy selection without a full schema migration. `ephemeral`
    /// is always `false` -- a resolved selection is a persisted/projected model,
    /// never a runtime-only provider handle.
    pub fn to_provider_config(&self) -> ProviderConfig {
        ProviderConfig {
            provider_type: self.provider_type.clone(),
            api_key: self.api_key.clone(),
            model: self.model.clone(),
            base_url: self.base_url.clone(),
            system_prompt: self.system_prompt.clone(),
            extra_headers: self.extra_headers.clone(),
            proxy: self.proxy.clone(),
            supports_vision: Some(self.supports_vision),
            user_agent: self.user_agent.clone(),
            context_window: self.context_window,
            max_tokens: self.max_tokens,
            thinking_type: self.thinking_type.clone(),
            thinking_keep: self.thinking_keep.clone(),
            reasoning_history: self.reasoning_history.clone(),
            reasoning_effort: self.reasoning_effort.clone(),
            reasoning_effort_levels: self.reasoning_effort_levels.clone(),
            thinking_enabled: self.thinking_enabled,
            thinking_budget: self.thinking_budget,
            skip_tls_verify: self.skip_tls_verify,
            ephemeral: false,
            capable_model: self.capable_model,
            retry_max_attempts: self.retry_max_attempts,
            model_mapping: self.model_mapping.clone(),
            timeout: None,
        }
    }
}

impl ProviderConfig {
    /// True if this provider's active model can accept image inputs.
    /// An explicit config value wins; otherwise use the backwards-compatible
    /// model-name heuristic.
    pub fn accepts_images(&self) -> bool {
        self.supports_vision
            .unwrap_or_else(|| crate::util::model_name_suggests_vision(&self.model))
    }

    /// Resolve the API key for this provider, taking environment variables into account.
    ///
    /// Resolution order:
    /// 1. If `api_key` is configured as a non-empty string:
    ///    a. If it contains `$`, expand environment variables (e.g. `$MY_KEY`, `${MY_KEY}`, `${MY_KEY:-default}`).
    ///    b. If it matches an existing environment variable name (e.g. `api_key = "MY_KEY_VAR"`), return its value.
    ///    c. Otherwise, return the configured string as a literal key.
    /// 2. If `api_key` is `None` or empty (or expanded to empty):
    ///    a. Check provider-type specific environment variables (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `OLLAMA_API_KEY`).
    ///    b. Check general environment variable `RUSTCODE_API_KEY`.
    pub fn resolved_api_key(&self) -> Option<String> {
        if let Some(key_str) = self.api_key.as_deref() {
            let trimmed = key_str.trim();
            if !trimmed.is_empty() {
                if trimmed.contains('$') {
                    let expanded = expand_env_vars(trimmed);
                    if !expanded.trim().is_empty() {
                        return Some(expanded);
                    }
                } else if let Ok(env_val) = std::env::var(trimmed) {
                    if !env_val.trim().is_empty() {
                        return Some(env_val);
                    }
                } else {
                    return Some(trimmed.to_string());
                }
            }
        }

        let env_var = match self.provider_type.as_str() {
            "openai" | "openai-compat" | "openai_compat" | "responses" => "OPENAI_API_KEY",
            "claude" | "anthropic" => "ANTHROPIC_API_KEY",
            "ollama" => "OLLAMA_API_KEY",
            "opencode" => "OPENCODE_API_KEY",
            _ => "",
        };

        if !env_var.is_empty() {
            if let Ok(val) = std::env::var(env_var) {
                if !val.trim().is_empty() {
                    return Some(val);
                }
            }
        }

        if let Ok(val) = std::env::var("RUSTCODE_API_KEY") {
            if !val.trim().is_empty() {
                return Some(val);
            }
        }

        None
    }
}

/// Expand environment variables in a string.
///
/// Supports `$VAR`, `${VAR}`, `${VAR:-default}` syntax.
pub fn expand_env_vars(s: &str) -> String {
    let mut result = String::with_capacity(s.len());
    let chars: Vec<char> = s.chars().collect();
    let mut i = 0;

    while i < chars.len() {
        if chars[i] == '$' && i + 1 < chars.len() {
            if chars[i + 1] == '{' {
                i += 2; // skip ${
                let mut var_name = String::new();
                let mut default_val = String::new();
                let mut has_default = false;

                while i < chars.len() && chars[i] != '}' {
                    if !has_default && chars[i] == ':' && i + 1 < chars.len() && chars[i + 1] == '-'
                    {
                        has_default = true;
                        i += 2;
                        continue;
                    }
                    if has_default {
                        default_val.push(chars[i]);
                    } else {
                        var_name.push(chars[i]);
                    }
                    i += 1;
                }
                if i < chars.len() && chars[i] == '}' {
                    i += 1; // skip }
                }

                let val = std::env::var(&var_name)
                    .ok()
                    .filter(|v| !v.trim().is_empty());
                if let Some(v) = val {
                    result.push_str(&v);
                } else if has_default {
                    result.push_str(&default_val);
                }
            } else if chars[i + 1].is_ascii_alphabetic() || chars[i + 1] == '_' {
                i += 1; // skip $
                let mut var_name = String::new();
                while i < chars.len() && (chars[i].is_ascii_alphanumeric() || chars[i] == '_') {
                    var_name.push(chars[i]);
                    i += 1;
                }
                if let Ok(val) = std::env::var(&var_name) {
                    result.push_str(&val);
                }
            } else {
                result.push(chars[i]);
                i += 1;
            }
        } else {
            result.push(chars[i]);
            i += 1;
        }
    }

    result
}

fn default_context_window() -> usize {
    128000
}

pub fn default_context_window_for(provider_type: &str) -> usize {
    match provider_type {
        "ollama" => 8000,
        _ => 128000,
    }
}

/// Wire-protocol family for a provider. Replaces the free-form `provider_type`
/// string at the dispatch boundary (`provider_factory.rs`) so unknown values
/// cannot silently fall through to the wrong adapter.
///
/// Historical string aliases are accepted on read (see `#[serde(alias = ...)]`)
/// so existing config files keep working.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum ProviderKind {
    #[serde(
        alias = "openai",
        alias = "openai-compatible",
        alias = "openai_compatible"
    )]
    OpenAiCompatible,
    #[serde(alias = "anthropic", alias = "claude", alias = "anthropic-compatible")]
    Anthropic,
    #[serde(alias = "ollama")]
    Ollama,
}

impl ProviderKind {
    /// Parse a raw `provider_type` string into a [`ProviderKind`].
    /// Unknown values yield `None` (the caller falls back to OpenAI-compatible
    /// with a warning, preserving the pre-existing default behaviour).
    pub fn from_type(s: &str) -> Option<Self> {
        let lowered = s.to_ascii_lowercase();
        match lowered.as_str() {
            "openai" | "openai-compatible" | "openai_compatible" => Some(Self::OpenAiCompatible),
            "anthropic" | "claude" | "anthropic-compatible" | "anthropic_compatible" => {
                Some(Self::Anthropic)
            }
            "ollama" => Some(Self::Ollama),
            _ => None,
        }
    }

    /// Canonical wire string for this kind (used in telemetry-free logs only).
    pub fn as_type_str(self) -> &'static str {
        match self {
            Self::OpenAiCompatible => "openai-compatible",
            Self::Anthropic => "anthropic",
            Self::Ollama => "ollama",
        }
    }
}

/// Upper bound on a model fallback chain length. Bounded on purpose: a long
/// chain multiplies request volume on the user's behalf, and almost every real
/// setup needs two or three targets at most. See FR-1.4 of
/// `docs/model-fallback-requirements.md`.
pub const MAX_MODEL_FALLBACK_CHAIN: usize = 4;

/// Maps a requested model alias to the wire model name sent to the provider.
/// Resolved once at the provider factory so adapters and drivers never see
/// aliases. An empty table is the identity mapping.
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
#[serde(transparent)]
pub struct ModelMapping(pub std::collections::HashMap<String, String>);

impl ModelMapping {
    /// Resolve `requested` to its wire name. Missing entries return `requested`
    /// unchanged.
    pub fn resolve<'a>(&'a self, requested: &'a str) -> &'a str {
        self.0
            .get(requested)
            .map(String::as_str)
            .unwrap_or(requested)
    }

    /// True when the table is empty (identity mapping). Used by the
    /// `skip_serializing_if` attribute so the field is omitted from config output.
    pub fn is_empty(&self) -> bool {
        self.0.is_empty()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    // ---- [providers.<name>.timeout] ----

    #[test]
    fn legacy_provider_config_without_timeout_still_loads() {
        // Backwards compatibility: every config written before the `timeout`
        // section existed must keep loading, and must keep the adapter defaults.
        let cfg: ProviderConfig = toml::from_str(
            r#"
                type = "openai"
                model = "deepseek-chat"
                api_key = "sk-test"
            "#,
        )
        .expect("legacy config must load");
        assert!(cfg.timeout.is_none());
    }

    #[test]
    fn timeout_section_parses_all_three_budgets() {
        let cfg: ProviderConfig = toml::from_str(
            r#"
                type = "openai"
                model = "deepseek-chat"
                api_key = "sk-test"

                [timeout]
                connect = 10
                request = 600
                idle = 300
            "#,
        )
        .expect("timeout section must parse");
        let timeout = cfg.timeout.expect("timeout present");
        assert_eq!(timeout.connect(), Some(std::time::Duration::from_secs(10)));
        assert_eq!(timeout.request(), Some(std::time::Duration::from_secs(600)));
        assert_eq!(timeout.idle(), Some(std::time::Duration::from_secs(300)));
    }

    #[test]
    fn timeout_section_accepts_partial_budgets() {
        // Only `idle` set: the other two must stay on the adapter defaults
        // rather than being coerced to zero.
        let cfg: ProviderConfig = toml::from_str(
            r#"
                type = "claude"
                model = "claude-sonnet-4-5"
                api_key = "sk-test"

                [timeout]
                idle = 45
            "#,
        )
        .expect("partial timeout must parse");
        let timeout = cfg.timeout.expect("timeout present");
        assert_eq!(timeout.idle(), Some(std::time::Duration::from_secs(45)));
        assert_eq!(timeout.connect(), None);
        assert_eq!(timeout.request(), None);
        assert!(!timeout.is_empty());
    }

    #[test]
    fn timeout_section_rejects_unknown_keys() {
        // `deny_unknown_fields`: a typo must fail loudly instead of silently
        // leaving the user with a timeout they never actually set.
        let result: Result<ProviderConfig, _> = toml::from_str(
            r#"
                type = "openai"
                model = "deepseek-chat"
                api_key = "sk-test"

                [timeout]
                idle = 300
                idel = 600
            "#,
        );
        assert!(result.is_err(), "a misspelled timeout key must be rejected");
    }

    #[test]
    fn timeout_section_is_omitted_when_unset() {
        // Serialization must not emit an empty `[timeout]` table into the
        // user's config.toml.
        let cfg: ProviderConfig = toml::from_str(
            r#"
                type = "openai"
                model = "deepseek-chat"
                api_key = "sk-test"
            "#,
        )
        .expect("parse");
        let serialized = toml::to_string(&cfg).expect("serialize");
        assert!(
            !serialized.contains("timeout"),
            "unset timeout must not be serialized: {serialized}"
        );
    }

    #[test]
    fn accepts_images_false_for_text_only_model() {
        // Regression for the user's GLM-5.1 case: heuristic rejects
        // text-only models so the TUI's Ctrl+V handler refuses image
        // paste before sending a doomed request.
        let toml_str = r#"
            type = "openai"
            model = "GLM-5.1"
            api_key = "sk-test"
            base_url = "https://api-ai.example.net/v1"
        "#;
        let cfg: ProviderConfig = toml::from_str(toml_str).expect("parse");
        assert!(!cfg.accepts_images());
    }

    #[test]
    fn accepts_images_true_via_heuristic_on_known_vision_model() {
        let toml_str = r#"
            type = "claude"
            model = "claude-sonnet-4-5"
            api_key = "sk-test"
        "#;
        let cfg: ProviderConfig = toml::from_str(toml_str).expect("parse");
        assert!(cfg.accepts_images());
    }

    #[test]
    fn explicit_vision_override_wins_over_auto_heuristic() {
        let enabled: ProviderConfig = toml::from_str(
            r#"
                type = "openai"
                model = "qwen3.8max"
                supports_vision = true
            "#,
        )
        .expect("parse enabled override");
        assert!(enabled.accepts_images());

        let disabled: ProviderConfig = toml::from_str(
            r#"
                type = "openai"
                model = "gpt-4o"
                supports_vision = false
            "#,
        )
        .expect("parse disabled override");
        assert!(!disabled.accepts_images());

        let auto: ProviderConfig = toml::from_str(
            r#"
                type = "openai"
                model = "gpt-4o"
            "#,
        )
        .expect("parse auto");
        assert_eq!(auto.supports_vision, None);
        assert!(!toml::to_string(&auto).unwrap().contains("supports_vision"));
    }

    #[test]
    fn thinking_fields_default_to_none() {
        let toml_str = r#"
            type = "claude"
            model = "claude-sonnet-4"
            base_url = "https://api.anthropic.com"
            context_window = 128000
        "#;
        let cfg: ProviderConfig = toml::from_str(toml_str).expect("parse");
        assert!(cfg.thinking_enabled.is_none());
        assert!(cfg.thinking_budget.is_none());
    }

    #[test]
    fn thinking_fields_parse_correctly() {
        let toml_str = r#"
            type = "claude"
            model = "claude-sonnet-4"
            base_url = "https://api.anthropic.com"
            context_window = 128000
            thinking_enabled = true
            thinking_budget = 20000
        "#;
        let cfg: ProviderConfig = toml::from_str(toml_str).expect("parse");
        assert_eq!(cfg.thinking_enabled, Some(true));
        assert_eq!(cfg.thinking_budget, Some(20000));
    }

    #[test]
    fn skip_tls_verify_defaults_to_false() {
        let toml_str = r#"
            type = "openai"
            model = "gpt-4o"
            api_key = "sk-test"
        "#;
        let cfg: ProviderConfig = toml::from_str(toml_str).expect("parse");
        assert!(
            !cfg.skip_tls_verify,
            "skip_tls_verify should default to false"
        );
    }

    #[test]
    fn skip_tls_verify_can_be_set_true() {
        let toml_str = r#"
            type = "openai"
            model = "gpt-4o"
            api_key = "sk-test"
            base_url = "https://self-signed.example.com/v1"
            skip_tls_verify = true
        "#;
        let cfg: ProviderConfig = toml::from_str(toml_str).expect("parse");
        assert!(cfg.skip_tls_verify, "skip_tls_verify should be true");
    }

    #[test]
    fn skip_tls_verify_not_serialized_when_false() {
        let cfg = ProviderConfig {
            provider_type: "openai".into(),
            api_key: Some("sk-test".into()),
            model: "gpt-4o".into(),
            base_url: None,
            system_prompt: None,
            supports_vision: None,
            user_agent: None,
            context_window: 128000,
            max_tokens: None,
            thinking_type: None,
            thinking_keep: None,
            reasoning_history: None,
            reasoning_effort: None,
            reasoning_effort_levels: None,
            thinking_enabled: None,
            thinking_budget: None,
            skip_tls_verify: false,
            extra_headers: None,
            proxy: None,
            ephemeral: false,
            capable_model: None,
            retry_max_attempts: None,
            model_mapping: Default::default(),
            timeout: None,
        };
        let serialized = toml::to_string(&cfg).expect("serialize");
        assert!(
            !serialized.contains("skip_tls_verify"),
            "skip_tls_verify should not be serialized when false"
        );
    }

    #[test]
    fn skip_tls_verify_serialized_when_true() {
        let cfg = ProviderConfig {
            provider_type: "openai".into(),
            api_key: Some("sk-test".into()),
            model: "gpt-4o".into(),
            base_url: Some("https://self-signed.example.com/v1".into()),
            system_prompt: None,
            extra_headers: None,
            proxy: None,
            supports_vision: None,
            user_agent: None,
            context_window: 128000,
            max_tokens: None,
            thinking_type: None,
            thinking_keep: None,
            reasoning_history: None,
            reasoning_effort: None,
            reasoning_effort_levels: None,
            thinking_enabled: None,
            thinking_budget: None,
            skip_tls_verify: true,
            ephemeral: false,
            capable_model: None,
            retry_max_attempts: None,
            model_mapping: Default::default(),
            timeout: None,
        };
        let serialized = toml::to_string(&cfg).expect("serialize");
        assert!(
            serialized.contains("skip_tls_verify = true"),
            "skip_tls_verify should be serialized when true"
        );
    }

    #[test]
    fn capable_model_round_trips_and_skips_none() {
        // Hand-written (or server-persisted) rank parses.
        let toml_str = r#"
            type = "openai"
            model = "GLM-5.2"
            base_url = "https://llm-api.example.com/v1"
            context_window = 200000
            capable_model = 1
        "#;
        let cfg: ProviderConfig = toml::from_str(toml_str).expect("parse");
        assert_eq!(cfg.capable_model, Some(1));
        // Round-trips on save, and `None` is not emitted (existing configs stay clean).
        let s = toml::to_string(&cfg).expect("serialize");
        assert!(s.contains("capable_model = 1"), "set rank must serialize");
        let none_cfg = ProviderConfig {
            capable_model: None,
            retry_max_attempts: None,
            ..cfg
        };
        let s2 = toml::to_string(&none_cfg).expect("serialize");
        assert!(!s2.contains("capable_model"), "None must not be serialized");
    }

    #[test]
    fn test_expand_env_vars() {
        std::env::set_var("TEST_ENV_VAR_1", "secret_key_value");
        std::env::set_var("TEST_ENV_VAR_2", "secondary_value");

        assert_eq!(expand_env_vars("$TEST_ENV_VAR_1"), "secret_key_value");
        assert_eq!(expand_env_vars("${TEST_ENV_VAR_1}"), "secret_key_value");
        assert_eq!(
            expand_env_vars("prefix_${TEST_ENV_VAR_1}_suffix"),
            "prefix_secret_key_value_suffix"
        );
        assert_eq!(
            expand_env_vars("${NON_EXISTENT_VAR:-fallback_value}"),
            "fallback_value"
        );
        assert_eq!(
            expand_env_vars("${TEST_ENV_VAR_1:-fallback_value}"),
            "secret_key_value"
        );
        assert_eq!(expand_env_vars("plain_literal_key"), "plain_literal_key");
    }

    #[test]
    fn test_resolved_api_key_env_expansion() {
        std::env::set_var("TEST_API_KEY_ENV", "sk-from-env-var");

        let cfg = ProviderConfig {
            provider_type: "openai".into(),
            api_key: Some("$TEST_API_KEY_ENV".into()),
            model: "gpt-4o".into(),
            base_url: None,
            system_prompt: None,
            supports_vision: None,
            user_agent: None,
            context_window: 128000,
            max_tokens: None,
            thinking_type: None,
            thinking_keep: None,
            reasoning_history: None,
            reasoning_effort: None,
            reasoning_effort_levels: None,
            thinking_enabled: None,
            thinking_budget: None,
            skip_tls_verify: false,
            extra_headers: None,
            proxy: None,
            ephemeral: false,
            capable_model: None,
            retry_max_attempts: None,
            model_mapping: Default::default(),
            timeout: None,
        };

        assert_eq!(cfg.resolved_api_key(), Some("sk-from-env-var".to_string()));
    }

    #[test]
    fn test_resolved_api_key_direct_env_name() {
        std::env::set_var("MY_CUSTOM_KEY_NAME", "sk-custom-123");

        let cfg = ProviderConfig {
            provider_type: "openai".into(),
            api_key: Some("MY_CUSTOM_KEY_NAME".into()),
            model: "gpt-4o".into(),
            base_url: None,
            system_prompt: None,
            supports_vision: None,
            user_agent: None,
            context_window: 128000,
            max_tokens: None,
            thinking_type: None,
            thinking_keep: None,
            reasoning_history: None,
            reasoning_effort: None,
            reasoning_effort_levels: None,
            thinking_enabled: None,
            thinking_budget: None,
            skip_tls_verify: false,
            extra_headers: None,
            proxy: None,
            ephemeral: false,
            capable_model: None,
            retry_max_attempts: None,
            model_mapping: Default::default(),
            timeout: None,
        };

        assert_eq!(cfg.resolved_api_key(), Some("sk-custom-123".to_string()));
    }

    #[test]
    fn test_resolved_api_key_fallback_to_standard_env() {
        std::env::set_var("OPENAI_API_KEY", "sk-openai-std");

        let cfg = ProviderConfig {
            provider_type: "openai".into(),
            api_key: None,
            model: "gpt-4o".into(),
            base_url: None,
            system_prompt: None,
            supports_vision: None,
            user_agent: None,
            context_window: 128000,
            max_tokens: None,
            thinking_type: None,
            thinking_keep: None,
            reasoning_history: None,
            reasoning_effort: None,
            reasoning_effort_levels: None,
            thinking_enabled: None,
            thinking_budget: None,
            skip_tls_verify: false,
            extra_headers: None,
            proxy: None,
            ephemeral: false,
            capable_model: None,
            retry_max_attempts: None,
            model_mapping: Default::default(),
            timeout: None,
        };

        assert_eq!(cfg.resolved_api_key(), Some("sk-openai-std".to_string()));
    }
}
