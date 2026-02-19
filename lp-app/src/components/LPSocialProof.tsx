interface SocialProofItem {
  metric: string;
  label: string;
}

interface Props {
  title: string;
  items: SocialProofItem[];
}

export default function LPSocialProof({ title, items }: Props) {
  return (
    <section className="bg-gray-50 py-16 sm:py-20">
      <div className="mx-auto max-w-5xl px-6">
        <h2 className="text-center text-2xl font-bold text-gray-900 sm:text-3xl">
          {title}
        </h2>
        <div className="mt-12 grid gap-8 sm:grid-cols-2 lg:grid-cols-4">
          {items.map((item, i) => (
            <div key={i} className="text-center">
              <p className="text-4xl font-bold text-blue-600">{item.metric}</p>
              <p className="mt-2 text-sm text-gray-600">{item.label}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
