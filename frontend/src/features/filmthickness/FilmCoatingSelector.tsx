import { TabsList, TabsTrigger } from "@/components/ui/tabs";
import { FILM_LAYERS } from "./film-overview-display";

export function FilmCoatingSelector({ selected }: { selected: string }) {
  return (
    <div className="film-stack-panel">
      <p className="film-stack-caption">
        Coating layer <span>Select to change chart</span>
      </p>
      <TabsList className="film-coating-stack" aria-label="Coating layers">
        {FILM_LAYERS.map((layer, index) => (
          <TabsTrigger className="film-stack-target" value={layer.code} key={layer.code}>
            <svg viewBox="0 0 40 34" aria-hidden="true" focusable="false">
              {[3, 2, 1, 0].map((plane) => (
                <path
                  key={plane}
                  d="M4 10 23 4 36 10 17 16Z"
                  transform={`translate(0 ${plane * 5})`}
                  className="film-stack-plane"
                  data-coating-plane={plane === index ? layer.code : undefined}
                  data-selected={plane === index && selected === layer.code}
                  data-layer={plane === index}
                />
              ))}
            </svg>
            <span>{layer.label}</span>
          </TabsTrigger>
        ))}
      </TabsList>
    </div>
  );
}
