import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { useQuery } from '@tanstack/react-query';
import { apiClient } from '../api/client';

export default function ImageLibrary() {
  const { data: images, isLoading } = useQuery({
    queryKey: ['images'],
    queryFn: async () => {
      const res = await apiClient.get('/jobs/images');
      return res.data;
    },
    refetchInterval: 3000
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight text-gray-900 dark:text-gray-100">Image Library</h1>
        <p className="text-gray-500 dark:text-gray-400">View and manage downloaded material images.</p>
      </div>
      
      {isLoading ? <div className="text-gray-500">Loading images...</div> : (
        <div className="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-4 gap-4">
          {images?.length === 0 ? (
            <div className="text-gray-500 col-span-full">No images found yet.</div>
          ) : (
            images?.map((img: any, i: number) => (
              <Card key={i} className="overflow-hidden">
                <div className="h-48 w-full bg-gray-100 dark:bg-gray-800 flex items-center justify-center overflow-hidden p-2">
                  <img
                    src={`http://127.0.0.1:8001/api/proxy-image?url=${encodeURIComponent(img.url)}`}
                    alt={img.name}
                    className="object-contain h-full w-full"
                    loading="lazy"
                  />
                </div>
                <CardContent className="p-4">
                  <p className="font-semibold text-sm truncate" title={img.name}>{img.name}</p>
                  <p className="text-xs text-gray-500 mt-1">{new Date(img.timestamp).toLocaleTimeString()}</p>
                </CardContent>
              </Card>
            ))
          )}
        </div>
      )}
    </div>
  );
}
