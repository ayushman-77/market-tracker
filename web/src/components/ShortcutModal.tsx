import type { FC } from 'react';
import { Command, X } from 'lucide-react';

interface ShortcutModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export const ShortcutModal: FC<ShortcutModalProps> = ({ isOpen, onClose }) => {
  if (!isOpen) return null;

  const shortcuts = [
    { key: 'm', desc: 'Switch between Markets Catalog and Chart Terminal' },
    { key: '/', desc: 'Focus search bar (questions or wallet leaderboard)' },
    { key: 'j', desc: 'Select next wallet in leaderboard' },
    { key: 'k', desc: 'Select previous wallet in leaderboard' },
    { key: 'Enter', desc: 'Open wallet drilldown modal' },
    { key: 'Esc', desc: 'Close modal or clear search' },
    { key: 'r', desc: 'Force resync orderbook and leaderboard snapshots' },
    { key: '1, 2, 3', desc: 'Quick-switch featured prediction markets' },
    { key: 'b', desc: 'Execute paper Buy market order (100 units)' },
    { key: 's', desc: 'Execute paper Sell market order (100 units)' },
    { key: '?', desc: 'Toggle keyboard shortcuts cheat sheet' },
  ];

  return (
    <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-xs flex items-center justify-center p-4">
      <div className="bg-[#11151F] border border-term-border rounded-lg shadow-2xl w-full max-w-md overflow-hidden font-mono">
        <div className="p-3 bg-[#0B0E14] border-b border-term-border flex items-center justify-between">
          <div className="flex items-center space-x-2">
            <Command className="w-4 h-4 text-sky-400" />
            <span className="text-xs font-semibold text-slate-200 uppercase">
              Keyboard Shortcuts & Controls
            </span>
          </div>
          <button
            onClick={onClose}
            className="p-1 text-slate-400 hover:text-white hover:bg-term-card rounded"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="p-4 space-y-2 text-xs divide-y divide-term-border/40">
          {shortcuts.map((s) => (
            <div key={s.key} className="pt-2 flex justify-between items-center">
              <span className="text-slate-400">{s.desc}</span>
              <kbd className="px-2 py-0.5 bg-[#141A24] border border-term-border rounded text-sky-400 font-bold shadow-xs">
                {s.key}
              </kbd>
            </div>
          ))}
        </div>

        <div className="p-2.5 bg-[#0B0E14] border-t border-term-border text-center text-[10px] text-slate-500">
          Designed for high-speed, keyboard-first quant workflows.
        </div>
      </div>
    </div>
  );
};
