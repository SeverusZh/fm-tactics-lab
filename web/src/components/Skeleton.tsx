interface SkeletonProps {
  label: string;
  variant?: "lines" | "rows";
  count?: number;
  className?: string;
}

export function Skeleton({ label, variant = "lines", count = 3, className }: SkeletonProps) {
  const itemCount = Math.max(1, Math.trunc(count));
  const classes = className === undefined || className === "" ? "skeleton" : `skeleton ${className}`;
  return (
    <div className={classes} role="status" aria-live="polite" data-testid="skeleton">
      <span className="skeleton-label">{label}</span>
      <div className={variant === "rows" ? "skeleton-rows" : "skeleton-lines"} aria-hidden="true">
        {Array.from({ length: itemCount }, (_, index) =>
          variant === "rows" ? (
            <div className="skeleton-row" key={index}>
              <span className="skeleton-block" />
              <span className="skeleton-block" />
              <span className="skeleton-block" />
            </div>
          ) : (
            <span className="skeleton-line" key={index} />
          ),
        )}
      </div>
    </div>
  );
}
