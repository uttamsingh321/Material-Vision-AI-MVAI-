function App() {
  return (
    <div className="min-h-screen bg-gray-50 flex flex-col items-center justify-center text-center p-4">
      <h1 className="text-4xl font-bold text-blue-600 mb-4">Material Vision AI (MVAI)</h1>
      <p className="text-lg text-gray-700 max-w-2xl">
        Intelligent automation platform to enrich Material Master Excel files with verified product images.
      </p>
      <div className="mt-8">
        <button className="bg-blue-600 text-white px-6 py-2 rounded-lg shadow hover:bg-blue-700 transition">
          Upload Excel File
        </button>
      </div>
    </div>
  );
}

export default App;
