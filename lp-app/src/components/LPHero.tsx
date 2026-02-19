interface Props {
  headline: string;
  subheadline: string;
  ctaText: string;
  ctaAction: string;
}

export default function LPHero({ headline, subheadline, ctaText, ctaAction }: Props) {
  return (
    <section className="relative bg-gradient-to-br from-blue-600 to-indigo-800 text-white">
      <div className="mx-auto max-w-4xl px-6 py-24 text-center sm:py-32">
        <h1 className="text-3xl font-bold tracking-tight sm:text-5xl leading-tight">
          {headline}
        </h1>
        <p className="mt-6 text-lg text-blue-100 sm:text-xl">
          {subheadline}
        </p>
        <div className="mt-10">
          <a
            href={ctaAction}
            className="inline-block rounded-lg bg-white px-8 py-4 text-lg font-semibold text-blue-700 shadow-lg hover:bg-blue-50 transition"
          >
            {ctaText}
          </a>
        </div>
      </div>
    </section>
  );
}
