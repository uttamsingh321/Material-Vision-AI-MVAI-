import React from 'react';
import { NavLink } from 'react-router-dom';
import { LayoutDashboard, Upload, Activity, CheckSquare, Image as ImageIcon, History, FileText, Server, Settings } from 'lucide-react';

export const Sidebar: React.FC = () => {
  const navItems = [
    { to: '/', icon: LayoutDashboard, label: 'Dashboard' },
    { to: '/upload', icon: Upload, label: 'Upload' },
    { to: '/review', icon: CheckSquare, label: 'Review Queue' },
    { to: '/library', icon: ImageIcon, label: 'Image Library' },
    { to: '/history', icon: History, label: 'Job History' },
    { to: '/logs', icon: FileText, label: 'Logs' },
    { to: '/providers', icon: Server, label: 'Providers' },
    { to: '/settings', icon: Settings, label: 'Settings' },
  ];

  return (
    <div className="w-64 bg-slate-900 text-white flex flex-col h-full border-r border-slate-800">
      <div className="p-6">
        <h1 className="text-xl font-bold flex items-center gap-2">
          <Activity className="text-indigo-400" /> MVAI
        </h1>
      </div>
      <nav className="flex-1 px-4 space-y-2 overflow-y-auto">
        {navItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2 rounded-md transition-colors ${
                isActive ? 'bg-indigo-600 text-white' : 'text-slate-300 hover:bg-slate-800 hover:text-white'
              }`
            }
          >
            <item.icon className="w-5 h-5" />
            {item.label}
          </NavLink>
        ))}
      </nav>
    </div>
  );
};
