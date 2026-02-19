interface FAQItem {
  question: string;
  answer: string;
}

interface Props {
  title: string;
  items: FAQItem[];
}

export default function LPFAQ({ title, items }: Props) {
  return (
    <section className="bg-white py-16 sm:py-20">
      <div className="mx-auto max-w-3xl px-6">
        <h2 className="text-center text-2xl font-bold text-gray-900 sm:text-3xl">
          {title}
        </h2>
        <dl className="mt-12 space-y-6">
          {items.map((item, i) => (
            <div key={i} className="rounded-lg border border-gray-200 p-6">
              <dt className="text-base font-semibold text-gray-900">
                Q. {item.question}
              </dt>
              <dd className="mt-3 text-sm text-gray-600 leading-relaxed">
                {item.answer}
              </dd>
            </div>
          ))}
        </dl>
      </div>
    </section>
  );
}
