import type { ReactNode } from "react";

interface Props {
  id?: string;
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  as?: "h2" | "h3";
  size?: "lg" | "md";
  className?: string;
}

export default function SectionHeading({
  id,
  title,
  description,
  action,
  as: Tag = "h2",
  size = "lg",
  className = "",
}: Props) {
  return (
    <div className={`flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between ${className}`}>
      <div className="min-w-0">
        <Tag
          id={id}
          className={
            size === "lg"
              ? "display text-[2.875rem] sm:text-[3.75rem] lg:text-[4.25rem]"
              : "heading text-[1.875rem] sm:text-[2.125rem]"
          }
        >
          {title}
        </Tag>
        {description ? <p className="mt-3 max-w-2xl text-[17px] leading-relaxed text-fg-2">{description}</p> : null}
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </div>
  );
}
