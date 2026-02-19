interface FeatureItem {
  icon: string;
  title: string;
  description: string;
}

interface Props {
  title: string;
  items: FeatureItem[];
}

export default function LPFeatures({ title, items }: Props) {
  return (
    <section className="bg-white py-16 sm:py-20">
      <div className="mx-auto max-w-5xl px-6">
        <h2 className="text-center text-2xl font-bold text-gray-900 sm:text-3xl">
          {title}
        </h2>
        <div className="mt-12 grid gap-8 sm:grid-cols-2 lg:grid-cols-3">
          {items.map((item, i) => (
            <div key={i} className="rounded-xl border border-gray-100 p-6 shadow-sm">
              <div className="text-3xl">{item.icon}</div>
              <h3 className="mt-4 text-lg font-semibold text-gray-900">
                {item.title}
              </h3>
              <p className="mt-2 text-sm text-gray-600 leading-relaxed">
                {item.description}
              </p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
