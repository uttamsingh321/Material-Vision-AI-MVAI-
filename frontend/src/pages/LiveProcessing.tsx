import { useWebSocket } from '../contexts/WebSocketContext';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Activity, Clock, Cpu, Server, ImageIcon, List } from 'lucide-react';
import { useEffect, useState } from 'react';

export default function LiveProcessing() {
  const { isConnected, lastMessage, foundCount, notFoundCount, logs } = useWebSocket();
  const [currentJob, setCurrentJob] = useState<any>(null);

  useEffect(() => {
    if (lastMessage) {
      if (lastMessage.type === 'job_update') {
        setCurrentJob(lastMessage.data);
      }
    }
  }, [lastMessage]);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-gray-900 dark:text-gray-100">Live Processing</h1>
          <p className="text-gray-500 dark:text-gray-400">Real-time view of worker activity.</p>
        </div>
        <div className="flex items-center gap-4">
          <a 
            href="http://127.0.0.1:8001/api/download/latest" 
            target="_blank"
            className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-md text-sm font-medium shadow-sm transition-colors"
          >
            Download Output
          </a>
          <div className="flex items-center gap-2">
            <span className="text-sm text-gray-500">WebSocket:</span>
            <div className={`px-2 py-1 rounded-full text-xs font-medium ${isConnected ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'}`}>
              {isConnected ? 'Connected' : 'Disconnected'}
            </div>
          </div>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-3 lg:grid-cols-6">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium">Current Job</CardTitle>
            <Activity className="h-4 w-4 text-blue-500" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{currentJob ? String(currentJob.id).substring(0,8) : 'None'}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium">Total Rows</CardTitle>
            <List className="h-4 w-4 text-indigo-500" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{currentJob?.total_items || '0'}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium">Progress</CardTitle>
            <Server className="h-4 w-4 text-green-500" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{currentJob ? `${currentJob.progress}%` : '0%'}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium">Processing Speed</CardTitle>
            <Cpu className="h-4 w-4 text-purple-500" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{currentJob ? `${currentJob.speed} it/m` : '0 it/m'}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium">Est. Remaining</CardTitle>
            <Clock className="h-4 w-4 text-yellow-500" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{currentJob?.eta || 'N/A'}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium">Image Success</CardTitle>
            <ImageIcon className="h-4 w-4 text-emerald-500" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-green-600">{foundCount}</div>
            <p className="text-xs text-red-500">{notFoundCount} not found</p>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Live Logs</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="bg-gray-900 text-green-400 p-4 rounded-md h-96 overflow-y-auto font-mono text-sm">
            {logs.length === 0 ? (
              <span className="text-gray-500">Waiting for logs...</span>
            ) : (
              logs.map((log, i) => (
                <div key={i} className="mb-1">{log}</div>
              ))
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
