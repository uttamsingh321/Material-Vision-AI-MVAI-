import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Activity, Database, CheckCircle, XCircle } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { apiClient } from '../api/client';

export default function Dashboard() {
  const { data, isLoading } = useQuery({
    queryKey: ['dashboard_stats'],
    queryFn: async () => {
      const res = await apiClient.get('/jobs/stats');
      return res.data;
    },
    refetchInterval: 3000
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight text-gray-900 dark:text-gray-100">Dashboard</h1>
        <p className="text-gray-500 dark:text-gray-400">Overview of your MVAI enterprise system.</p>
      </div>
      
      {isLoading ? <div className="text-gray-500">Loading live stats...</div> : (
      <>
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Total Materials</CardTitle>
            <Database className="h-4 w-4 text-gray-500" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{data?.total_materials || 0}</div>
            <p className="text-xs text-gray-500">Processed so far</p>
          </CardContent>
        </Card>
        
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Running Jobs</CardTitle>
            <Activity className="h-4 w-4 text-blue-500" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{data?.running_jobs || 0}</div>
            <p className="text-xs text-gray-500">Currently executing</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Completed Jobs</CardTitle>
            <CheckCircle className="h-4 w-4 text-green-500" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{data?.completed_jobs || 0}</div>
            <p className="text-xs text-gray-500">Finished successfully</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Failed Jobs</CardTitle>
            <XCircle className="h-4 w-4 text-red-500" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{data?.failed_jobs || 0}</div>
            <p className="text-xs text-gray-500">Needs review</p>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-7">
        <Card className="col-span-4">
          <CardHeader>
            <CardTitle>Processing Trend</CardTitle>
          </CardHeader>
          <CardContent className="h-[300px] flex items-center justify-center text-gray-500">
            [Chart waiting for sufficient data]
          </CardContent>
        </Card>

        <Card className="col-span-3">
          <CardHeader>
            <CardTitle>Recent Activity</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              {data?.recent_activity?.length > 0 ? data.recent_activity.map((act: any, i: number) => (
                <div key={i} className="flex items-center gap-4">
                  <div className="w-2 h-2 bg-blue-500 rounded-full" />
                  <div className="flex-1 space-y-1">
                    <p className="text-sm font-medium leading-none">{act.message}</p>
                    <p className="text-sm text-gray-500">{new Date(act.time).toLocaleTimeString()}</p>
                  </div>
                </div>
              )) : (
                <div className="text-gray-500">No recent activity.</div>
              )}
            </div>
          </CardContent>
        </Card>
      </div>
      </>
      )}
    </div>
  );
}
