import { CalendarDays, ChartNoAxesCombined, Globe2, Layers3, Newspaper, Settings2, ShieldCheck } from 'lucide-react';

const sections = [
  { id: 'overview', label: 'Overview', icon: ChartNoAxesCombined },
  { id: 'analysis', label: 'AI analyst', icon: Layers3 },
  { id: 'timeframe-analysis', label: 'Timeframe analysis', icon: ChartNoAxesCombined },
  { id: 'macro', label: 'Macro intelligence', icon: Globe2 },
  { id: 'sentiment', label: 'Sentiment & news', icon: Newspaper },
  { id: 'calendar', label: 'Economic calendar', icon: CalendarDays },
  { id: 'evidence', label: 'Evidence quality', icon: ShieldCheck },
  { id: 'settings', label: 'Settings & providers', icon: Settings2 },
];

export function Navigation() {
  return (
    <aside className="section-rail">
      <nav aria-label="Workspace sections">
        <p className="rail-heading">Research</p>
        <ul>
          {sections.map(({ id, label, icon: Icon }) => (
            <li key={id}><a href={`#${id}`}><Icon aria-hidden="true" size={18} /><span>{label}</span></a></li>
          ))}
        </ul>
      </nav>
      <div className="rail-note"><ShieldCheck aria-hidden="true" size={18} />
        <p>Evidence before conclusions.</p><span>Research only. No trade execution.</span>
      </div>
    </aside>
  );
}
