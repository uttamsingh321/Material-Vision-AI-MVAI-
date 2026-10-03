import os

base_dir = r"c:\Users\uttam.singh1\Desktop\Material Vision AI (MVAI)\frontend\src\pages"

jobs_page = """import { useQuery } from '@tanstack/react-query';
import { getJobs } from '../api/jobs';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Play, Pause, Square, AlertCircle, RefreshCw } from 'lucide-react';

export default function JobsPage() {
  const { data: jobs, isLoading, isError, refetch } = useQuery({
    queryKey: ['jobs'],
    queryFn: getJobs,
    staleTime: 10000
  });

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-gray-900 dark:text-gray-100">Jobs</h1>
          <p className="text-gray-500 dark:text-gray-400">Manage and monitor processing jobs.</p>
        </div>
        <Button onClick={() => refetch()} variant="outline" className="gap-2">
          <RefreshCw className="h-4 w-4" /> Refresh
        </Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>All Jobs</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="flex justify-center py-8 text-gray-500">Loading jobs...</div>
          ) : isError ? (
            <div className="flex justify-center py-8 text-red-500 items-center gap-2">
              <AlertCircle className="h-5 w-5" /> Failed to load jobs.
            </div>
          ) : jobs?.length === 0 ? (
            <div className="text-center py-8 text-gray-500">No jobs found.</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm text-left">
                <thead className="text-xs text-gray-700 uppercase bg-gray-50 dark:bg-gray-800 dark:text-gray-300">
                  <tr>
                    <th className="px-6 py-3">ID</th>
                    <th className="px-6 py-3">Status</th>
                    <th className="px-6 py-3">Progress</th>
                    <th className="px-6 py-3">Created</th>
                    <th className="px-6 py-3 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {jobs?.map((job: any) => (
                    <tr key={job.id} className="bg-white border-b dark:bg-gray-900 dark:border-gray-700">
                      <td className="px-6 py-4 font-medium text-gray-900 dark:text-white whitespace-nowrap">
                        {job.id.substring(0, 8)}
                      </td>
                      <td className="px-6 py-4">
                        <span className={`px-2 py-1 rounded text-xs font-medium 
                          ${job.status === 'RUNNING' ? 'bg-blue-100 text-blue-800' : 
                            job.status === 'COMPLETED' ? 'bg-green-100 text-green-800' : 
                            job.status === 'FAILED' ? 'bg-red-100 text-red-800' : 
                            'bg-gray-100 text-gray-800'}`}>
                          {job.status}
                        </span>
                      </td>
                      <td className="px-6 py-4">
                        <div className="w-full bg-gray-200 rounded-full h-2.5 dark:bg-gray-700 mt-2">
                          <div className="bg-blue-600 h-2.5 rounded-full" style={{ width: `${job.progress || 0}%` }}></div>
                        </div>
                      </td>
                      <td className="px-6 py-4">
                        {new Date(job.created_at).toLocaleString()}
                      </td>
                      <td className="px-6 py-4 text-right space-x-2">
                        {job.status === 'RUNNING' && (
                          <button className="text-gray-500 hover:text-yellow-600"><Pause className="h-4 w-4" /></button>
                        )}
                        {(job.status === 'PAUSED' || job.status === 'FAILED') && (
                          <button className="text-gray-500 hover:text-green-600"><Play className="h-4 w-4" /></button>
                        )}
                        {['RUNNING', 'PAUSED', 'QUEUED'].includes(job.status) && (
                          <button className="text-gray-500 hover:text-red-600"><Square className="h-4 w-4" /></button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
"""

with open(os.path.join(base_dir, "JobsPage.tsx"), 'w', encoding='utf-8') as f:
    f.write(jobs_page)

print("JobsPage scaffolded.")
