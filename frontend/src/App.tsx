import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
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
import LoginPage from './pages/LoginPage';
import { useAuth } from './contexts/AuthContext';

// Basic Protected Route wrapper
function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { isAuthenticated } = useAuth();
  if (!isAuthenticated) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

function App() {
  return (
    <Router>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        
        <Route path="/" element={<ProtectedRoute><Layout /></ProtectedRoute>}>

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
