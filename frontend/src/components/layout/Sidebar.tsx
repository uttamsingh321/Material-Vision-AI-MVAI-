import { Link, useLocation } from 'react-router-dom';
import { 
  LayoutDashboard, Upload, List, Activity, CheckSquare, 
  Image as ImageIcon, FileBarChart, History, Globe, 
  Settings, Users, HeartPulse
} from 'lucide-react';
import { clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';

const navigation = [
  { name: 'Dashboard', href: '/', icon: LayoutDashboard },
  { name: 'Upload', href: '/upload', icon: Upload },
  { name: 'Jobs', href: '/jobs', icon: List },
  { name: 'Processing', href: '/processing', icon: Activity },
  { name: 'Review Queue', href: '/review', icon: CheckSquare },
  { name: 'Image Library', href: '/library', icon: ImageIcon },
  { name: 'Reports', href: '/reports', icon: FileBarChart },
  { name: 'Audit Logs', href: '/audit', icon: History },
  { name: 'Provider Status', href: '/providers', icon: Globe },
  { name: 'Settings', href: '/settings', icon: Settings },
  { name: 'Users', href: '/users', icon: Users },
  { name: 'System Health', href: '/health', icon: HeartPulse },
];

export default function Sidebar() {
  const location = useLocation();

  return (
    <div className="w-64 bg-white dark:bg-gray-800 border-r border-gray-200 dark:border-gray-700 flex flex-col hidden md:flex">
      <div className="h-16 flex items-center px-6 border-b border-gray-200 dark:border-gray-700">
        <span className="text-lg font-bold">MVAI Enterprise</span>
      </div>
      <nav className="flex-1 overflow-y-auto py-4">
        <ul className="space-y-1 px-3">
          {navigation.map((item) => {
            const isActive = location.pathname === item.href;
            return (
              <li key={item.name}>
                <Link
                  to={item.href}
                  className={twMerge(
                    clsx(
                      'flex items-center gap-3 px-3 py-2 rounded-md text-sm font-medium transition-colors',
                      isActive 
                        ? 'bg-blue-50 text-blue-700 dark:bg-blue-900/50 dark:text-blue-200' 
                        : 'text-gray-700 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-700'
                    )
                  )}
                >
                  <item.icon className="h-5 w-5" />
                  {item.name}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>
    </div>
  );
}
