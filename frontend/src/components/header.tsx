import { Shield } from "lucide-react";

export function Header() {
  return (
    <header className="border-b border-border/50 bg-card/50 backdrop-blur-xl sticky top-0 z-50">
      <div className="container mx-auto px-4 py-4 max-w-7xl flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="relative">
            <div className="absolute inset-0 bg-primary/20 rounded-lg blur-md" />
            <div className="relative bg-primary/10 border border-primary/20 rounded-lg p-2">
              <Shield className="w-6 h-6 text-primary" />
            </div>
          </div>
          <div>
            <h1 className="text-xl font-bold tracking-tight">
              Secure<span className="text-primary">Gate</span>
            </h1>
            <p className="text-xs text-muted-foreground">
              PHI De-Identification Engine
            </p>
          </div>
        </div>
        <div className="flex items-center gap-4">
          <div className="hidden sm:flex items-center gap-2 text-xs text-muted-foreground bg-secondary/50 px-3 py-1.5 rounded-full">
            <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
            HIPAA Safe Harbor Compliant
          </div>
          <div className="text-xs text-muted-foreground">
            by <span className="text-primary font-medium">Cognitva.ai</span>
          </div>
        </div>
      </div>
    </header>
  );
}
