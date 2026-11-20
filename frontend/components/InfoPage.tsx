import Footer from "@/components/Footer";

interface Props {
  title: string;
  intro?: React.ReactNode;
  updated?: string;
  children: React.ReactNode;
}

export default function InfoPage({ title, intro, updated, children }: Props) {
  return (
    <div className="flex min-h-screen flex-col pt-16">
      <header className="on-ink grain-ink bg-ink text-white">
        <div className="wrap pb-12 pt-7 sm:pb-16 sm:pt-9">
          <div aria-hidden className="h-[3px] bg-white" />
          <h1 className="display-xl mt-8 overflow-hidden pb-[0.14em] text-[clamp(3.25rem,9vw,7rem)]">
            <span className="rise">{title}</span>
          </h1>
          {intro ? <p className="mt-5 max-w-2xl text-lg leading-relaxed text-ink-muted sm:text-xl">{intro}</p> : null}
          {updated ? (
            <p className="mt-6 text-[15px] text-ink-muted">
              Last updated <span className="font-semibold text-white">{updated}</span>
            </p>
          ) : null}
        </div>
      </header>
      <main className="wrap flex-1 pb-24 pt-12 sm:pt-16">
        <div className="max-w-[44rem] space-y-14">{children}</div>
      </main>
      <Footer />
    </div>
  );
}

export function InfoSection({ id, title, children }: { id?: string; title: string; children: React.ReactNode }) {
  return (
    <section id={id} className="scroll-mt-24 border-t-[3px] border-fg pt-6">
      <h2 className="heading text-[1.875rem] sm:text-[2.125rem]">{title}</h2>
      <div className="mt-4 space-y-4 text-[17px] leading-[1.65] text-fg-2 [&_a:hover]:bg-brand [&_a]:font-semibold [&_a]:text-fg [&_a]:underline [&_a]:decoration-brand [&_a]:decoration-[3px] [&_a]:underline-offset-[3px] [&_li]:pl-1 [&_strong]:font-semibold [&_strong]:text-fg [&_ul]:list-disc [&_ul]:space-y-2.5 [&_ul]:pl-5 [&_ul]:marker:text-fg">
        {children}
      </div>
    </section>
  );
}
