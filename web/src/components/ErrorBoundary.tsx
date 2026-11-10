import { Component, ErrorInfo, ReactNode } from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  public state: State = {
    hasError: false,
    error: null,
  };

  public static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  public componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('Uncaught error in component tree:', error, errorInfo);
  }

  public render() {
    if (this.state.hasError) {
      return (
        <div className="flex flex-col items-center justify-center min-h-screen bg-[#0B0E14] text-slate-200 p-6 font-mono">
          <div className="bg-[#141A24] border border-red-800/80 rounded-lg p-6 max-w-lg w-full text-center shadow-xl">
            <div className="inline-flex p-3 bg-red-950/60 rounded-full border border-red-700/50 mb-4 text-red-400">
              <AlertTriangle className="w-8 h-8" />
            </div>
            <h2 className="text-lg font-bold text-white mb-2">Terminal Render Exception</h2>
            <p className="text-xs text-red-400 mb-4 bg-black/40 p-3 rounded font-mono text-left overflow-x-auto">
              {this.state.error?.message || 'An unexpected rendering error occurred.'}
            </p>
            <button
              onClick={() => window.location.reload()}
              className="inline-flex items-center gap-2 px-4 py-2 bg-sky-600 hover:bg-sky-500 text-white rounded text-xs font-semibold transition-colors"
            >
              <RefreshCw className="w-4 h-4" />
              <span>Reload Terminal</span>
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}

