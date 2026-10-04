import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '../api/client';
import { Edit2, Trash2, Check, X, Plus } from 'lucide-react';
import { useState } from 'react';

export default function ImageLibrary() {
  const queryClient = useQueryClient();
  const [editingName, setEditingName] = useState<string | null>(null);
  const [editValue, setEditValue] = useState('');
  
  const [isAdding, setIsAdding] = useState(false);
  const [newName, setNewName] = useState('');
  const [newUrl, setNewUrl] = useState('');

  const { data: images, isLoading } = useQuery({
    queryKey: ['images'],
    queryFn: async () => {
      const res = await apiClient.get('/jobs/images');
      return res.data;
    },
    refetchInterval: 3000
  });

  const deleteMutation = useMutation({
    mutationFn: (name: string) => apiClient.delete('/jobs/images', { data: { name } }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['images'] })
  });

  const updateMutation = useMutation({
    mutationFn: (data: { old_name: string, new_name: string }) => apiClient.put('/jobs/images', data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['images'] });
      setEditingName(null);
    }
  });

  const addMutation = useMutation({
    mutationFn: (data: { name: string, url: string }) => apiClient.post('/jobs/images', data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['images'] });
      setIsAdding(false);
      setNewName('');
      setNewUrl('');
    }
  });

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-gray-900 dark:text-gray-100">Image Library History</h1>
          <p className="text-gray-500 dark:text-gray-400">View, edit, and manage history of all verified industrial images.</p>
        </div>
        <button onClick={() => setIsAdding(!isAdding)} className="flex items-center gap-2 bg-blue-600 text-white px-4 py-2 rounded shadow hover:bg-blue-700">
          <Plus className="w-4 h-4" /> Add Image
        </button>
      </div>

      {isAdding && (
        <Card className="p-4 bg-gray-50 dark:bg-gray-800 border-dashed">
          <div className="flex gap-4 items-end">
            <div className="flex-1">
              <label className="block text-sm font-medium mb-1">Image Name</label>
              <input type="text" value={newName} onChange={e => setNewName(e.target.value)} className="w-full border rounded p-2 text-sm dark:bg-gray-700 dark:border-gray-600" placeholder="e.g. Copper Wire" />
            </div>
            <div className="flex-1">
              <label className="block text-sm font-medium mb-1">Image URL</label>
              <input type="text" value={newUrl} onChange={e => setNewUrl(e.target.value)} className="w-full border rounded p-2 text-sm dark:bg-gray-700 dark:border-gray-600" placeholder="https://example.com/image.jpg" />
            </div>
            <button onClick={() => addMutation.mutate({ name: newName, url: newUrl })} disabled={!newName || !newUrl} className="bg-green-600 text-white px-6 py-2 rounded shadow hover:bg-green-700 disabled:opacity-50 h-10">
              Save
            </button>
          </div>
        </Card>
      )}
      
      {isLoading ? <div className="text-gray-500">Loading images...</div> : (
        <div className="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-4 gap-4">
          {images?.length === 0 ? (
            <div className="text-gray-500 col-span-full">No images found yet.</div>
          ) : (
            images?.map((img: any, i: number) => (
              <Card key={i} className="overflow-hidden flex flex-col group">
                <div className="h-48 w-full bg-gray-100 dark:bg-gray-800 flex items-center justify-center overflow-hidden p-2 relative">
                  <img
                    src={`http://127.0.0.1:8001/api/proxy-image?url=${encodeURIComponent(img.url)}`}
                    alt={img.name}
                    className="object-contain h-full w-full"
                    loading="lazy"
                  />
                  <div className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity flex gap-1">
                    <button onClick={() => deleteMutation.mutate(img.name)} className="p-1.5 bg-red-500 text-white rounded hover:bg-red-600 shadow">
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                </div>
                <CardContent className="p-4 flex-1">
                  {editingName === img.name ? (
                    <div className="flex items-center gap-2">
                      <input 
                        type="text" 
                        value={editValue} 
                        onChange={e => setEditValue(e.target.value)}
                        className="w-full text-sm border rounded px-2 py-1 dark:bg-gray-700 dark:border-gray-600"
                        autoFocus
                      />
                      <button onClick={() => updateMutation.mutate({ old_name: img.name, new_name: editValue })} className="text-green-600 hover:text-green-700">
                        <Check className="w-4 h-4" />
                      </button>
                      <button onClick={() => setEditingName(null)} className="text-red-500 hover:text-red-600">
                        <X className="w-4 h-4" />
                      </button>
                    </div>
                  ) : (
                    <div className="flex items-center justify-between group/title cursor-pointer" onClick={() => { setEditingName(img.name); setEditValue(img.name); }}>
                      <p className="font-semibold text-sm truncate" title={img.name}>{img.name}</p>
                      <Edit2 className="w-3 h-3 text-gray-400 opacity-0 group-hover/title:opacity-100" />
                    </div>
                  )}
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
