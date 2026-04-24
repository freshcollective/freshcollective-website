interface SectionHeadingProps {
  title: string;
  subtitle?: string;
  align?: "left" | "center";
  className?: string;
}

export default function SectionHeading({
  title,
  subtitle,
  align = "left",
  className = "",
}: SectionHeadingProps) {
  return (
    <div className={`${align === "center" ? "text-center" : "text-left"} ${className}`}>
      <h2 className="font-serif text-3xl text-navy-900 md:text-4xl">{title}</h2>
      {subtitle && (
        <p className="mt-3 text-base text-[#4A5568] md:text-lg">{subtitle}</p>
      )}
    </div>
  );
}
