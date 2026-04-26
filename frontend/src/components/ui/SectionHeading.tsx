interface SectionHeadingProps {
  title: string;
  subtitle?: string;
  align?: "left" | "center";
  className?: string;
  dark?: boolean;
}

export default function SectionHeading({
  title,
  subtitle,
  align = "left",
  className = "",
  dark = false,
}: SectionHeadingProps) {
  const isCenter = align === "center";
  return (
    <div className={`${isCenter ? "text-center" : "text-left"} ${className}`}>
      <div className={`mb-3 h-px w-8 bg-gold-500 ${isCenter ? "mx-auto" : ""}`} />
      <h2 className={`font-serif text-3xl md:text-4xl ${dark ? "text-white" : "text-navy-900"}`}>
        {title}
      </h2>
      {subtitle && (
        <p className={`mt-3 text-base md:text-lg ${dark ? "text-navy-300" : "text-[#4A5568]"}`}>
          {subtitle}
        </p>
      )}
    </div>
  );
}
