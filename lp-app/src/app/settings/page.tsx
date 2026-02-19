"use client";

import { useEffect, useState } from "react";
import AppShell from "../../components/AppShell";

interface Setting {
  key: string;
  value: string;
}

export default function SettingsPage() {
  const [settings, setSettings] = useState<Setting[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    fetch("/api/settings")
      .then((r) => r.json())
      .then((d) => setSettings(d.settings || []))
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
  const ideaSettings = settings.filter((s) =>
    ["target_industries", "trend_keywords", "ideas_per_run"].includes(s.key)
  );
  const salesSettings = settings.filter((s) =>
    ["form_sales_per_day", "lp_base_url"].includes(s.key)
  );
  const systemSettings = settings.filter((s) =>
    ["slack_notification", "auto_approve", "risk_threshold"].includes(s.key)
  );
  const otherSettings = settings.filter(
    (s) => ![...ideaSettings, ...salesSettings, ...systemSettings].find((is) => is.key === s.key)
  );

  return (
    <AppShell>
      <header className="sticky top-0 z-30 hidden lg:flex h-14 items-center justify-between border-b border-white/[.06] bg-[#0a0a0f]/80 px-6 backdrop-blur-xl">
        <h1 className="text-sm font-medium text-white/60">Settings</h1>
        <button
          onClick={handleSave}
          disabled={saving}
          className="rounded-lg bg-blue-600 px-4 py-1.5 text-xs font-medium text-white transition-all hover:bg-blue-500 disabled:opacity-50"
        >
          {saving ? "Saving..." : saved ? "\u2713 Saved" : "Save Changes"}
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
            <p className="mt-4 text-sm text-white/30">No settings available yet</p>
            <p className="mt-1 text-[11px] text-white/15">Run setup_sheets.py first to initialize settings</p>
          </div>
        ) : (
          <>
            {/* Idea Generation Settings */}
            <SettingsSection title="Idea Generation" description="Configure how business ideas are generated">
              {ideaSettings.map((s) => (
                <SettingRow key={s.key} setting={s} onChange={updateSetting} />
              ))}
            </SettingsSection>

            {/* Sales Settings */}
            <SettingsSection title="Form Sales" description="Outbound sales automation settings">
              {salesSettings.map((s) => (
                <SettingRow key={s.key} setting={s} onChange={updateSetting} />
              ))}
            </SettingsSection>

            {/* System Settings */}
            {systemSettings.length > 0 && (
              <SettingsSection title="System" description="Notification and automation settings">
                {systemSettings.map((s) => (
                  <SettingRow key={s.key} setting={s} onChange={updateSetting} />
                ))}
              </SettingsSection>
            )}

            {/* Other Settings */}
            {otherSettings.length > 0 && (
              <SettingsSection title="Other" description="Additional configuration">
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
                {saving ? "Saving..." : saved ? "\u2713 Saved" : "Save Changes"}
              </button>
            </div>
          </>
        )}
      </main>
    </AppShell>
  );
}

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

const SETTING_LABELS: Record<string, { label: string; description: string }> = {
  target_industries: { label: "ターゲット業界", description: "事業案生成の対象業界（カンマ区切り）" },
  trend_keywords: { label: "トレンドキーワード", description: "事業案生成に使うキーワード" },
  ideas_per_run: { label: "生成数/回", description: "1回の実行で生成する事業案の数" },
  form_sales_per_day: { label: "フォーム送信数/日", description: "1日あたりの最大フォーム送信数" },
  lp_base_url: { label: "LP ベースURL", description: "LP公開先のベースURL" },
  slack_notification: { label: "Slack通知", description: "enabled / disabled" },
  auto_approve: { label: "自動承認", description: "事業案の自動承認（enabled / disabled）" },
  risk_threshold: { label: "リスク閾値", description: "SNS投稿・フォーム営業のリスク判定レベル（low / medium / high）" },
};

function SettingRow({
  setting,
  onChange,
}: {
  setting: Setting;
  onChange: (key: string, value: string) => void;
}) {
  const meta = SETTING_LABELS[setting.key] || {
    label: setting.key.replace(/_/g, " "),
    description: "",
  };

  return (
    <div className="flex items-center gap-4 rounded-xl bg-black/20 p-3">
      <div className="min-w-0 flex-1">
        <p className="text-xs font-medium capitalize">{meta.label}</p>
        {meta.description && (
          <p className="text-[10px] text-white/30">{meta.description}</p>
        )}
      </div>
      <input
        type="text"
        value={setting.value}
        onChange={(e) => onChange(setting.key, e.target.value)}
        className="w-48 rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-xs text-white outline-none focus:border-blue-500/50 transition-colors"
      />
    </div>
  );
}
