import { useState, useEffect } from 'react';
import Dashboard from './components/Dashboard';
import { Sun, Moon, Monitor, Eye } from 'lucide-react';

type Theme = 'light' | 'dark' | 'system';

function App() {
  const [theme, setTheme] = useState<Theme>(() => {
    return (localStorage.getItem('gatelook-theme') as Theme) || 'system';
  });

  const [themeMenuOpen, setThemeMenuOpen] = useState(false);

  useEffect(() => {
    const root = document.documentElement;
    localStorage.setItem('gatelook-theme', theme);

    const updateTheme = () => {
      if (theme === 'dark') {
        root.classList.add('dark');
      } else if (theme === 'light') {
        root.classList.remove('dark');
      } else {
        const systemIsDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
        if (systemIsDark) {
          root.classList.add('dark');
        } else {
          root.classList.remove('dark');
        }
      }
    };

    updateTheme();

    if (theme === 'system') {
      const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
      const handleChange = () => updateTheme();
      mediaQuery.addEventListener('change', handleChange);
      return () => mediaQuery.removeEventListener('change', handleChange);
    }
    return;
  }, [theme]);

  const activeThemeIcon = () => {
    if (theme === 'light') return <Sun className="h-4 w-4 text-amber-500" />;
    if (theme === 'dark') return <Moon className="h-4 w-4 text-blue-400" />;
    return <Monitor className="h-4 w-4 text-zinc-500 dark:text-zinc-400" />;
  };

  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-zinc-950 text-zinc-800 dark:text-zinc-200 flex flex-col transition-colors duration-200">
      {/* Header Bar */}
      <header className="glass-panel sticky top-0 z-50 px-6 py-4 flex items-center justify-between shadow-sm shadow-zinc-100 dark:shadow-none">
        <div className="flex items-center space-x-3">
          {/* Logo Icon */}
          <div className="h-9 w-9 rounded-lg bg-blue-600/10 dark:bg-blue-500/10 flex items-center justify-center text-blue-600 dark:text-blue-400">
            <Eye className="h-5 w-5 animate-pulse" />
          </div>
          <div>
            <h1 className="text-xl font-bold tracking-wide text-zinc-900 dark:text-white flex items-center gap-1">
              GATE<span className="text-blue-600 dark:text-blue-500 font-extrabold">LOOK</span>
            </h1>
            <p className="text-[10px] text-zinc-500 dark:text-zinc-400 tracking-wider uppercase font-semibold">
              Vehicle Security & OCR Intelligence
            </p>
          </div>
        </div>
        
        <div className="flex items-center space-x-4">
          <div className="hidden md:flex flex-col text-right">
            <span className="text-xs text-zinc-800 dark:text-zinc-200 font-semibold">Station-01 ACTIVE</span>
            <span className="text-[10px] text-emerald-600 dark:text-emerald-400 font-mono flex items-center justify-end gap-1">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 glow-active"></span>
              Inference Node Online
            </span>
          </div>
          
          <div className="h-8 w-[1px] bg-zinc-200 dark:bg-zinc-800 hidden md:block"></div>
          
          {/* Theme Selector Widget */}
          <div className="relative">
            <button
              onClick={() => setThemeMenuOpen(!themeMenuOpen)}
              className="p-2 rounded-lg bg-zinc-100 hover:bg-zinc-200 dark:bg-zinc-900 dark:hover:bg-zinc-850 border border-zinc-200 dark:border-zinc-800 transition flex items-center justify-center"
              title="Change theme"
            >
              {activeThemeIcon()}
            </button>
            
            {themeMenuOpen && (
              <>
                <div 
                  className="fixed inset-0 z-10" 
                  onClick={() => setThemeMenuOpen(false)}
                ></div>
                <div className="absolute right-0 mt-2 w-32 rounded-lg bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 shadow-xl z-20 overflow-hidden py-1">
                  <button
                    onClick={() => { setTheme('light'); setThemeMenuOpen(false); }}
                    className={`w-full px-3 py-2 text-left text-xs flex items-center space-x-2 hover:bg-zinc-50 dark:hover:bg-zinc-850 ${theme === 'light' ? 'font-bold text-blue-600 dark:text-blue-400 bg-zinc-50 dark:bg-zinc-850' : 'text-zinc-700 dark:text-zinc-300'}`}
                  >
                    <Sun className="h-3.5 w-3.5" />
                    <span>Light</span>
                  </button>
                  <button
                    onClick={() => { setTheme('dark'); setThemeMenuOpen(false); }}
                    className={`w-full px-3 py-2 text-left text-xs flex items-center space-x-2 hover:bg-zinc-50 dark:hover:bg-zinc-850 ${theme === 'dark' ? 'font-bold text-blue-600 dark:text-blue-400 bg-zinc-50 dark:bg-zinc-850' : 'text-zinc-700 dark:text-zinc-300'}`}
                  >
                    <Moon className="h-3.5 w-3.5" />
                    <span>Dark</span>
                  </button>
                  <button
                    onClick={() => { setTheme('system'); setThemeMenuOpen(false); }}
                    className={`w-full px-3 py-2 text-left text-xs flex items-center space-x-2 hover:bg-zinc-50 dark:hover:bg-zinc-850 ${theme === 'system' ? 'font-bold text-blue-600 dark:text-blue-400 bg-zinc-50 dark:bg-zinc-850' : 'text-zinc-700 dark:text-zinc-300'}`}
                  >
                    <Monitor className="h-3.5 w-3.5" />
                    <span>System</span>
                  </button>
                </div>
              </>
            )}
          </div>

          <div className="px-3 py-1.5 rounded-lg bg-zinc-100 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 text-[10px] text-zinc-500 dark:text-zinc-400 font-mono font-bold tracking-wider">
            v1.1-PRO
          </div>
        </div>
      </header>

      {/* Workspace Panel */}
      <main className="flex-1 p-6 flex flex-col space-y-6 max-w-7xl mx-auto w-full">
        <Dashboard />
      </main>

      {/* Footer */}
      <footer className="border-t border-zinc-200 dark:border-zinc-900 py-6 text-center text-xs text-zinc-500 dark:text-zinc-500">
        &copy; {new Date().getFullYear()} Gatelook. Built for real-time edge security.
      </footer>
    </div>
  );
}

export default App;
