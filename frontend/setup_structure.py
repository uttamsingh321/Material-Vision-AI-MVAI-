import os

def create_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)

base_dir = r"c:\Users\uttam.singh1\Desktop\Material Vision AI (MVAI)\frontend\src"

files = {
    "App.tsx": """import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import Layout from './components/layout/Layout';
import Dashboard from './pages/Dashboard';
import UploadPage from './pages/UploadPage';
import JobsPage from './pages/JobsPage';
import LiveProcessing from './pages/LiveProcessing';
import ReviewQueue from './pages/ReviewQueue';
import ImageLibrary from './pages/ImageLibrary';
import Reports from './pages/Reports';
import AuditLogs from './pages/AuditLogs';
import ProviderStatus from './pages/ProviderStatus';
import Settings from './pages/Settings';
import Users from './pages/Users';
import SystemHealth from './pages/SystemHealth';

function App() {
  return (
    <Router>
      <Routes>
        <Route path="/" element={<Layout />}>
          <Route index element={<Dashboard />} />
          <Route path="upload" element={<UploadPage />} />
          <Route path="jobs" element={<JobsPage />} />
          <Route path="processing" element={<LiveProcessing />} />
          <Route path="review" element={<ReviewQueue />} />
          <Route path="library" element={<ImageLibrary />} />
          <Route path="reports" element={<Reports />} />
          <Route path="audit" element={<AuditLogs />} />
          <Route path="providers" element={<ProviderStatus />} />
          <Route path="settings" element={<Settings />} />
          <Route path="users" element={<Users />} />
          <Route path="health" element={<SystemHealth />} />
        </Route>
      </Routes>
    </Router>
  );
}

export default App;
""",
    "components/layout/Layout.tsx": """import { Outlet } from 'react-router-dom';
import Sidebar from './Sidebar';
import Topbar from './Topbar';

export default function Layout() {
  return (
    <div className="flex h-screen bg-gray-50 dark:bg-gray-900 text-gray-900 dark:text-gray-100">
      <Sidebar />
      <div className="flex flex-col flex-1 overflow-hidden">
        <Topbar />
        <main className="flex-1 overflow-y-auto p-4 md:p-6 lg:p-8">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
""",
    "components/layout/Sidebar.tsx": """import { Link, useLocation } from 'react-router-dom';
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
""",
    "components/layout/Topbar.tsx": """import { Bell, Search, User } from 'lucide-react';

export default function Topbar() {
  return (
    <header className="h-16 bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 flex items-center justify-between px-6">
      <div className="flex items-center gap-4 flex-1">
        <div className="relative w-64">
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-gray-500" />
          <input
            type="text"
            placeholder="Search..."
            className="w-full pl-9 pr-4 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-md bg-gray-50 dark:bg-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
      </div>
      <div className="flex items-center gap-4">
        <button className="text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200">
          <Bell className="h-5 w-5" />
        </button>
        <button className="h-8 w-8 rounded-full bg-gray-200 dark:bg-gray-700 flex items-center justify-center">
          <User className="h-5 w-5 text-gray-600 dark:text-gray-300" />
        </button>
      </div>
    </header>
  );
}
""",
}

# Create placeholder pages
pages = [
    "Dashboard", "UploadPage", "JobsPage", "LiveProcessing", "ReviewQueue", 
    "ImageLibrary", "Reports", "AuditLogs", "ProviderStatus", "Settings", 
    "Users", "SystemHealth"
]

for page in pages:
    files[f"pages/{page}.tsx"] = f"""export default function {page}() {{
  return (
    <div>
      <h1 className="text-2xl font-bold mb-4">{page}</h1>
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-6 border border-gray-200 dark:border-gray-700">
        <p className="text-gray-500 dark:text-gray-400">Content for {page} goes here.</p>
      </div>
    </div>
  );
}}
"""

for rel_path, content in files.items():
    create_file(os.path.join(base_dir, rel_path), content)

print("Setup complete.")
