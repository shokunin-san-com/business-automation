"use client";

import { useEffect, useState } from "react";
import AppShell from "../../components/AppShell";

interface Setting {
  key: string;
  value: string;
}

// ── UI type definitions ──────────────────────────────────────────────────────

type SettingUIType = "text" | "number" | "textarea" | "toggle" | "select";

interface SettingMeta {
  label: string;
  description: string;
  type?: SettingUIType;
  options?: { value: string; label: string }[];
  placeholder?: string;
  rows?: number;
  suffix?: string;
}

const SETTING_META: Record<string, SettingMeta> = {
  // Sender info
  sender_name: { label: "送信者名", description: "フォーム営業の差出人名" },
  sender_email: { label: "メールアドレス", description: "返信先メールアドレス" },
  sender_company: { label: "会社名", description: "フォーム営業で使用する社名" },
  // Idea generation
  target_industries: { label: "ターゲット業界", description: "事業案生成の対象業界（カンマ区切り）" },
  trend_keywords: { label: "トレンドキーワード", description: "事業案生成に使うキーワード" },
  ideas_per_run: { label: "生成数/回", description: "1回の実行で生成する事業案の数", type: "number", suffix: "件" },
  idea_direction_notes: { label: "方向性メモ", description: "事業案生成の方向性・考えていること（自由記述、AIプロンプトに反映）", type: "textarea", rows: 3, placeholder: "例: 初期投資を抑えて短期回収できるSaaSモデルを優先したい" },
  // Form sales
  form_sales_per_day: { label: "フォーム送信数/日", description: "1日あたりの最大フォーム送信数", type: "number", suffix: "件" },
  lp_base_url: { label: "LP ベースURL", description: "LP公開先のベースURL" },
  // Exploration & Selection
  exploration_markets: { label: "探索対象市場", description: "市場リサーチの対象（カンマ区切り）" },
  competitors_per_market: { label: "競合分析数/市場", description: "V2: 競合20社分析の目標企業数", type: "number", suffix: "社" },
  market_direction_notes: { label: "方向性メモ", description: "市場探索・選定の方向性・考えていること（自由記述、AIプロンプトに反映）", type: "textarea", rows: 3, placeholder: "例: 稟議が短く早期に売上がたつ市場を優先したい" },
  // SNS
  sns_posts_per_day: { label: "SNS投稿数/日", description: "1日あたりのSNS投稿数", type: "number", suffix: "件" },
  // CEO profile
  use_ceo_profile: { label: "CEO経歴スコアリング", description: "有効にするとCEO経歴に基づいて事業案がスコアリングされます", type: "toggle" },
  ceo_profile_json: { label: "CEO経歴・プロフィール", description: "自由記述でOK。経歴・強み・得意業界・資格などを書いてください", type: "textarea", rows: 6, placeholder: "例:\n岡部。M&Aフルサイクル経験（ソーシング〜PMI〜売却）。\n建設・インフラの設備設計〜施工管理の実務あり。\n得意業界: 建設、エネルギー、M&A、人材紹介\n資格: 第二種電気工事士、有料職業紹介事業" },
  // Kill criteria
  kill_criteria_enabled: { label: "損切り判定", description: "有効にすると低パフォーマンス事業を自動検出します", type: "toggle" },
  kill_criteria_days: { label: "判定期間", description: "この日数経過後に損切り評価を実施", type: "number", suffix: "日" },
  kill_criteria_min_cv: { label: "最低CV数", description: "この数未満のCV数で損切り候補に", type: "number", suffix: "件" },
  kill_criteria_min_score: { label: "最低スコア", description: "この値未満のスコアで損切り候補に", type: "number", suffix: "点" },
  // Budget
  monthly_ad_budget: { label: "月間広告予算", description: "Google Ads の月間予算上限", type: "number", suffix: "円" },
  ads_daily_budget: { label: "日次広告予算", description: "キャンペーンあたりの日次予算", type: "number", suffix: "円" },
  // System
  slack_notification: { label: "Slack通知", description: "パイプライン実行結果をSlackに通知します", type: "toggle" },
  auto_approve: { label: "自動承認", description: "生成された事業案を自動で承認します", type: "toggle" },
  risk_threshold: {
    label: "リスク閾値",
    description: "SNS投稿・フォーム営業のリスク判定レベル",
    type: "select",
    options: [
      { value: "low", label: "低（厳格）" },
      { value: "medium", label: "中（標準）" },
      { value: "high", label: "高（寛容）" },
    ],
  },
};

// ── Helpers ──────────────────────────────────────────────────────────────────

/** Check if a string value is truthy (covers true/enabled/on/yes) */
function isTruthy(v: string): boolean {
  return ["true", "enabled", "on", "yes", "1"].includes(v.toLowerCase().trim());
}
/** Convert boolean back to the format the setting uses */
function boolToValue(current: string, on: boolean): string {
  // Preserve the existing format (true/false vs enabled/disabled)
  if (current === "enabled" || current === "disabled") return on ? "enabled" : "disabled";
  if (current === "on" || current === "off") return on ? "on" : "off";
  return on ? "true" : "false";
}

// ── Main component ──────────────────────────────────────────────────────────

export default function SettingsPage() {
  const [settings, setSettings] = useState<Setting[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    fetch("/api/settings")
      .then((r) => r.json())
      .then((d) => {
        const fetched: Setting[] = d.settings || [];
        const requiredKeys = [
          { key: "sender_name", value: "" },
          { key: "sender_email", value: "" },
          { key: "sender_company", value: "" },
        ];
        const existingKeys = new Set(fetched.map((s) => s.key));
        for (const req of requiredKeys) {
          if (!existingKeys.has(req.key)) {
            fetched.unshift(req);
          }
        }
        setSettings(fetched);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const updateSetting = (key: string, value: string) => {
    setSettings((prev) =>
      prev.map((s) => (s.key === key ? { ...s, value } : s))
    );
    setSaved(false);
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      await fetch("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ settings }),
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } finally {
      setSaving(false);
    }
  };

  // Group settings for display
  const senderSettings = settings.filter((s) =>
    ["sender_name", "sender_email", "sender_company"].includes(s.key)
  );
  const ideaSettings = settings.filter((s) =>
    ["target_industries", "trend_keywords", "ideas_per_run", "idea_direction_notes"].includes(s.key)
  );
  const explorationSettings = settings.filter((s) =>
    ["exploration_markets", "competitors_per_market", "market_direction_notes"].includes(s.key)
  );
  const salesSettings = settings.filter((s) =>
    ["form_sales_per_day", "lp_base_url"].includes(s.key)
  );
  const snsSettings = settings.filter((s) =>
    ["sns_posts_per_day"].includes(s.key)
  );
  const ceoSettings = settings.filter((s) =>
    ["use_ceo_profile", "ceo_profile_json"].includes(s.key)
  );
  const killSettings = settings.filter((s) =>
    ["kill_criteria_enabled", "kill_criteria_days", "kill_criteria_min_cv", "kill_criteria_min_score"].includes(s.key)
  );
  const budgetSettings = settings.filter((s) =>
    ["monthly_ad_budget", "ads_daily_budget"].includes(s.key)
  );
  const systemSettings = settings.filter((s) =>
    ["slack_notification", "auto_approve", "risk_threshold"].includes(s.key)
  );
  const knownKeys = new Set([
    ...senderSettings, ...ideaSettings, ...explorationSettings, ...salesSettings,
    ...snsSettings, ...ceoSettings, ...killSettings, ...budgetSettings, ...systemSettings,
  ].map((s) => s.key));
  const otherSettings = settings.filter((s) => !knownKeys.has(s.key));

  return (
    <AppShell>
      <header className="sticky top-0 z-30 hidden lg:flex h-14 items-center justify-between border-b border-white/[.06] bg-[#0a0a0f]/80 px-6 backdrop-blur-xl">
        <h1 className="text-sm font-medium text-white/60">設定</h1>
        <button
          onClick={handleSave}
          disabled={saving}
          className="rounded-lg bg-blue-600 px-4 py-1.5 text-xs font-medium text-white transition-all hover:bg-blue-500 disabled:opacity-50"
        >
          {saving ? "保存中..." : saved ? "\u2713 保存しました" : "変更を保存"}
        </button>
      </header>

      <main className="mx-auto max-w-3xl space-y-6 p-6">
        {loading ? (
          <div className="flex h-40 items-center justify-center">
            <div className="h-6 w-6 animate-spin rounded-full border-2 border-white/20 border-t-blue-500" />
          </div>
        ) : settings.length === 0 ? (
          <div className="flex flex-col items-center justify-center rounded-2xl border border-white/[.06] bg-white/[.02] py-20">
            <svg className="h-12 w-12 text-white/10" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.324.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 011.37.49l1.296 2.247a1.125 1.125 0 01-.26 1.431l-1.003.827c-.293.24-.438.613-.431.992a6.759 6.759 0 010 .255c-.007.378.138.75.43.99l1.005.828c.424.35.534.954.26 1.43l-1.298 2.247a1.125 1.125 0 01-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.57 6.57 0 01-.22.128c-.331.183-.581.495-.644.869l-.213 1.28c-.09.543-.56.941-1.11.941h-2.594c-.55 0-1.02-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 01-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 01-1.369-.49l-1.297-2.247a1.125 1.125 0 01.26-1.431l1.004-.827c.292-.24.437-.613.43-.992a6.932 6.932 0 010-.255c.007-.378-.138-.75-.43-.99l-1.004-.828a1.125 1.125 0 01-.26-1.43l1.297-2.247a1.125 1.125 0 011.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.087.22-.128.332-.183.582-.495.644-.869l.214-1.281z" />
              <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
            </svg>
            <p className="mt-4 text-sm text-white/30">設定がまだありません</p>
            <p className="mt-1 text-[11px] text-white/15">setup_sheets.py を実行して初期設定してください</p>
          </div>
        ) : (
          <>
            {senderSettings.length > 0 && (
              <SettingsSection title="📧 送信者情報" description="フォーム営業で使用される送信者の情報">
                {senderSettings.map((s) => (
                  <SettingRow key={s.key} setting={s} onChange={updateSetting} />
                ))}
              </SettingsSection>
            )}

            <SettingsSection title="💡 事業案生成" description="事業案の自動生成に関する設定">
              {ideaSettings.map((s) => (
                <SettingRow key={s.key} setting={s} onChange={updateSetting} />
              ))}
            </SettingsSection>

            {explorationSettings.length > 0 && (
              <SettingsSection title="🔍 市場探索・選定" description="市場リサーチ・競合分析に関する設定">
                {explorationSettings.map((s) => (
                  <SettingRow key={s.key} setting={s} onChange={updateSetting} />
                ))}
              </SettingsSection>
            )}

            <SettingsSection title="✉️ フォーム営業" description="自動フォーム営業に関する設定">
              {salesSettings.map((s) => (
                <SettingRow key={s.key} setting={s} onChange={updateSetting} />
              ))}
            </SettingsSection>

            {snsSettings.length > 0 && (
              <SettingsSection title="📱 SNS投稿" description="SNS自動投稿に関する設定">
                {snsSettings.map((s) => (
                  <SettingRow key={s.key} setting={s} onChange={updateSetting} />
                ))}
              </SettingsSection>
            )}

            {ceoSettings.length > 0 && (
              <SettingsSection title="👤 CEO経歴プロファイラー" description="CEO経歴に基づく事業案スコアリング設定">
                {ceoSettings.map((s) => (
                  <SettingRow key={s.key} setting={s} onChange={updateSetting} />
                ))}
              </SettingsSection>
            )}

            {killSettings.length > 0 && (
              <SettingsSection title="🛑 損切りジャッジ" description="低パフォーマンス事業の自動検出基準">
                {killSettings.map((s) => (
                  <SettingRow key={s.key} setting={s} onChange={updateSetting} />
                ))}
              </SettingsSection>
            )}

            {budgetSettings.length > 0 && (
              <SettingsSection title="💰 広告予算" description="Google Ads 予算設定">
                {budgetSettings.map((s) => (
                  <SettingRow key={s.key} setting={s} onChange={updateSetting} />
                ))}
              </SettingsSection>
            )}

            {systemSettings.length > 0 && (
              <SettingsSection title="⚙️ システム" description="通知・自動化に関する設定">
                {systemSettings.map((s) => (
                  <SettingRow key={s.key} setting={s} onChange={updateSetting} />
                ))}
              </SettingsSection>
            )}

            {otherSettings.length > 0 && (
              <SettingsSection title="📋 その他" description="その他の設定項目">
                {otherSettings.map((s) => (
                  <SettingRow key={s.key} setting={s} onChange={updateSetting} />
                ))}
              </SettingsSection>
            )}

            {/* Mobile save button */}
            <div className="lg:hidden">
              <button
                onClick={handleSave}
                disabled={saving}
                className="w-full rounded-xl bg-blue-600 px-4 py-3 text-sm font-medium text-white transition-all hover:bg-blue-500 disabled:opacity-50"
              >
                {saving ? "保存中..." : saved ? "\u2713 保存しました" : "変更を保存"}
              </button>
            </div>
          </>
        )}
      </main>
    </AppShell>
  );
}

// ── Section wrapper ─────────────────────────────────────────────────────────

function SettingsSection({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-2xl border border-white/[.06] bg-white/[.02] p-5">
      <div className="mb-4">
        <h3 className="text-sm font-medium">{title}</h3>
        <p className="mt-0.5 text-[11px] text-white/30">{description}</p>
      </div>
      <div className="space-y-3">{children}</div>
    </section>
  );
}

// ── Toggle switch component ─────────────────────────────────────────────────

function ToggleSwitch({ on, onToggle }: { on: boolean; onToggle: (v: boolean) => void }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      onClick={() => onToggle(!on)}
      className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none ${
        on ? "bg-blue-600" : "bg-white/10"
      }`}
    >
      <span
        className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow-sm ring-0 transition duration-200 ease-in-out ${
          on ? "translate-x-5" : "translate-x-0"
        }`}
      />
    </button>
  );
}

// ── Smart setting row ───────────────────────────────────────────────────────

function SettingRow({
  setting,
  onChange,
}: {
  setting: Setting;
  onChange: (key: string, value: string) => void;
}) {
  const meta: SettingMeta = SETTING_META[setting.key] || {
    label: setting.key.replace(/_/g, " "),
    description: "",
  };

  // Determine UI type
  const uiType: SettingUIType = meta.type || (setting.value.length > 100 ? "textarea" : "text");

  // ── Toggle switch ──
  if (uiType === "toggle") {
    const on = isTruthy(setting.value);
    return (
      <div className="flex items-center gap-4 rounded-xl bg-black/20 p-3">
        <div className="min-w-0 flex-1">
          <p className="text-xs font-medium">{meta.label}</p>
          {meta.description && <p className="text-[10px] text-white/30">{meta.description}</p>}
        </div>
        <div className="flex items-center gap-2">
          <span className={`text-[10px] ${on ? "text-blue-400" : "text-white/25"}`}>
            {on ? "ON" : "OFF"}
          </span>
          <ToggleSwitch on={on} onToggle={(v) => onChange(setting.key, boolToValue(setting.value, v))} />
        </div>
      </div>
    );
  }

  // ── Select / dropdown ──
  if (uiType === "select" && meta.options) {
    return (
      <div className="flex items-center gap-4 rounded-xl bg-black/20 p-3">
        <div className="min-w-0 flex-1">
          <p className="text-xs font-medium">{meta.label}</p>
          {meta.description && <p className="text-[10px] text-white/30">{meta.description}</p>}
        </div>
        <select
          value={setting.value}
          onChange={(e) => onChange(setting.key, e.target.value)}
          className="rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-xs text-white outline-none focus:border-blue-500/50 transition-colors cursor-pointer"
        >
          {meta.options.map((opt) => (
            <option key={opt.value} value={opt.value} className="bg-[#1a1a2e]">
              {opt.label}
            </option>
          ))}
        </select>
      </div>
    );
  }

  // ── Textarea ──
  if (uiType === "textarea") {
    return (
      <div className="flex flex-col gap-2 rounded-xl bg-black/20 p-3">
        <div>
          <p className="text-xs font-medium">{meta.label}</p>
          {meta.description && <p className="text-[10px] text-white/30">{meta.description}</p>}
        </div>
        <textarea
          value={setting.value}
          onChange={(e) => onChange(setting.key, e.target.value)}
          rows={meta.rows || 3}
          placeholder={meta.placeholder}
          className="w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-xs text-white outline-none focus:border-blue-500/50 transition-colors resize-y"
        />
      </div>
    );
  }

  // ── Number input ──
  if (uiType === "number") {
    return (
      <div className="flex items-center gap-4 rounded-xl bg-black/20 p-3">
        <div className="min-w-0 flex-1">
          <p className="text-xs font-medium">{meta.label}</p>
          {meta.description && <p className="text-[10px] text-white/30">{meta.description}</p>}
        </div>
        <div className="flex items-center gap-1.5">
          <input
            type="number"
            value={setting.value}
            onChange={(e) => onChange(setting.key, e.target.value)}
            min={0}
            className="w-24 rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-xs text-white text-right outline-none focus:border-blue-500/50 transition-colors [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
          />
          {meta.suffix && <span className="text-[10px] text-white/30">{meta.suffix}</span>}
        </div>
      </div>
    );
  }

  // ── Default text input ──
  return (
    <div className="flex items-center gap-4 rounded-xl bg-black/20 p-3">
      <div className="min-w-0 flex-1">
        <p className="text-xs font-medium">{meta.label}</p>
        {meta.description && <p className="text-[10px] text-white/30">{meta.description}</p>}
      </div>
      <input
        type="text"
        value={setting.value}
        onChange={(e) => onChange(setting.key, e.target.value)}
        placeholder={meta.placeholder}
        className="w-48 rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-xs text-white outline-none focus:border-blue-500/50 transition-colors"
      />
    </div>
  );
}
