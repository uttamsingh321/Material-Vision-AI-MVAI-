import React from 'react';

export const TopBar: React.FC = () => {
  return (
    <header className="h-16 bg-white dark:bg-slate-900 border-b border-slate-200 dark:border-slate-800 flex items-center justify-between px-6">
      <h2 className="text-lg font-semibold text-slate-800 dark:text-white">Material Vision AI</h2>
      <div className="flex items-center gap-4">
        {/* Dark mode toggle should be handled by a context, but we will keep it simple here */}
        <div className="w-8 h-8 rounded-full bg-slate-200 dark:bg-slate-700 flex items-center justify-center text-sm font-medium">
          U
        </div>
      </div>
    </header>
  );
};
