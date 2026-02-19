interface Props {
  companyName: string;
}

export default function LPFooter({ companyName }: Props) {
  const year = new Date().getFullYear();
  return (
    <footer className="bg-gray-900 py-8 text-center text-sm text-gray-400">
      <p>&copy; {year} {companyName}. All rights reserved.</p>
    </footer>
  );
}
