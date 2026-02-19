"use client";

import { useState, type FormEvent } from "react";

interface Props {
  ctaText: string;
  email: string;
  businessId: string;
}

export default function LPContactForm({ ctaText, email, businessId }: Props) {
  const [submitted, setSubmitted] = useState(false);

  function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const data = new FormData(form);
    const name = data.get("name") as string;
    const company = data.get("company") as string;
    const userEmail = data.get("email") as string;
    const message = data.get("message") as string;

    const subject = encodeURIComponent(`[${businessId}] ${company} ${name}様からのお問い合わせ`);
    const body = encodeURIComponent(
      `会社名: ${company}\nお名前: ${name}\nメール: ${userEmail}\n\n${message}`
    );
    window.location.href = `mailto:${email}?subject=${subject}&body=${body}`;
    setSubmitted(true);

    // GA4 event
    if (typeof window !== "undefined" && (window as any).gtag) {
      (window as any).gtag("event", "form_submit", {
        event_category: "conversion",
        event_label: businessId,
      });
    }
  }

  if (submitted) {
    return (
      <section className="bg-blue-600 py-16 text-center text-white">
        <p className="text-xl font-semibold">お問い合わせありがとうございます。</p>
        <p className="mt-2 text-blue-100">メーラーが開きます。そのまま送信してください。</p>
      </section>
    );
  }

  return (
    <section id="contact" className="bg-gradient-to-br from-blue-600 to-indigo-800 py-16 sm:py-20">
      <div className="mx-auto max-w-xl px-6">
        <h2 className="text-center text-2xl font-bold text-white sm:text-3xl">
          {ctaText}
        </h2>
        <form onSubmit={handleSubmit} className="mt-10 space-y-4">
          <input
            type="text"
            name="company"
            placeholder="会社名"
            required
            className="w-full rounded-lg border-0 px-4 py-3 text-gray-900 shadow-sm placeholder:text-gray-400"
          />
          <input
            type="text"
            name="name"
            placeholder="お名前"
            required
            className="w-full rounded-lg border-0 px-4 py-3 text-gray-900 shadow-sm placeholder:text-gray-400"
          />
          <input
            type="email"
            name="email"
            placeholder="メールアドレス"
            required
            className="w-full rounded-lg border-0 px-4 py-3 text-gray-900 shadow-sm placeholder:text-gray-400"
          />
          <textarea
            name="message"
            rows={4}
            placeholder="ご質問・ご相談内容"
            className="w-full rounded-lg border-0 px-4 py-3 text-gray-900 shadow-sm placeholder:text-gray-400"
          />
          <button
            type="submit"
            className="w-full rounded-lg bg-white px-6 py-4 text-lg font-semibold text-blue-700 shadow-lg hover:bg-blue-50 transition"
          >
            {ctaText}
          </button>
        </form>
      </div>
    </section>
  );
}
