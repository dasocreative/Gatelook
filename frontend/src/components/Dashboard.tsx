import React, { useState, useEffect, useRef } from 'react';
import { 
  Play, Square, Upload, Video, RefreshCw, Search, 
  TrendingUp, Palette, Car, AlertCircle
} from 'lucide-react';
import { 
  ResponsiveContainer, AreaChart, Area, XAxis, YAxis, Tooltip, 
  Cell, PieChart, Pie
} from 'recharts';

// Core Dynamic host resolution
const HOSTNAME = typeof window !== 'undefined' ? window.location.hostname : 'localhost';
const API_BASE = `http://${HOSTNAME}:8000/api/v1`;
const WS_BASE = `ws://${HOSTNAME}:8000/api/v1`;

interface LogEntry {
  id: string;
  timestamp: string;
  vehicle_type: string;
  vehicle_model: string;
  vehicle_color: string;
  plate_number: string;
  confidence_score: number;
  crop_image_url: string;
}

interface StatsData {
  total_today: number;
  vehicle_types: { name: string; value: number }[];
  vehicle_colors: { name: string; value: number }[];
  hourly_traffic: { hour: string; count: number }[];
}

export default function Dashboard() {
  // Ingestion States
  const [feedState, setFeedState] = useState<'idle' | 'streaming' | 'completed' | 'error'>('idle');
  const [rtspUrl, setRtspUrl] = useState('');
  const [sessionID, setSessionID] = useState<string | null>(null);
  const [streamFrame, setStreamFrame] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  
  // Real-time Event Detections (WebSocket)
  const [liveDetections, setLiveDetections] = useState<LogEntry[]>([]);
  
  // Database Query States
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [totalLogs, setTotalLogs] = useState(0);
  const [stats, setStats] = useState<StatsData>({
    total_today: 0,
    vehicle_types: [],
    vehicle_colors: [],
    hourly_traffic: []
  });
  
  // Filters
  const [searchFilter, setSearchFilter] = useState('');
  const [colorFilter, setColorFilter] = useState('');
  const [typeFilter, setTypeFilter] = useState('');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [page, setPage] = useState(1);
  const limit = 10;

  const fileInputRef = useRef<HTMLInputElement>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const rightSideTableRef = useRef<HTMLDivElement>(null);

  // Fetch Database Logs
  const fetchLogs = async () => {
    try {
      const offset = (page - 1) * limit;
      const params = new URLSearchParams({
        limit: limit.toString(),
        offset: offset.toString()
      });
      
      if (searchFilter) params.append('search', searchFilter);
      if (colorFilter) params.append('color', colorFilter);
      if (typeFilter) params.append('vehicle_type', typeFilter);
      if (startDate) params.append('start_date', new Date(startDate).toISOString());
      if (endDate) params.append('end_date', new Date(endDate).toISOString());
      
      const res = await fetch(`${API_BASE}/logs?${params.toString()}`);
      const data = await res.json();
      setLogs(data.data);
      setTotalLogs(data.total);
    } catch (err) {
      console.error("Failed to query historical logs:", err);
    }
  };

  // Fetch Chart Stats
  const fetchStats = async () => {
    try {
      const res = await fetch(`${API_BASE}/stats`);
      const data = await res.json();
      setStats(data);
    } catch (err) {
      console.error("Failed to query statistics:", err);
    }
  };

  // Initialize Data
  useEffect(() => {
    fetchLogs();
    fetchStats();
    
    // Refresh stats every 30s
    const interval = setInterval(fetchStats, 30000);
    return () => clearInterval(interval);
  }, [page, searchFilter, colorFilter, typeFilter, startDate, endDate]);

  // Connect WebSocket stream
  const connectWebSocket = (sessId: string) => {
    if (wsRef.current) wsRef.current.close();
    
    setFeedState('streaming');
    setLiveDetections([]);
    setStreamFrame(null);
    setErrorMessage(null);
    setSessionID(sessId);
    
    const ws = new WebSocket(`${WS_BASE}/ws/stream/${sessId}`);
    wsRef.current = ws;
    
    ws.onmessage = (event) => {
      const payload = JSON.parse(event.data);
      
      if (payload.type === 'frame') {
        setStreamFrame(payload.image);
      } else if (payload.type === 'new_detection') {
        const item: LogEntry = payload.data;
        // Inject into websocket table
        setLiveDetections(prev => [item, ...prev].slice(0, 50));
        
        // Auto scroll websocket sidebar down/up to keep focus
        if (rightSideTableRef.current) {
          rightSideTableRef.current.scrollTop = 0;
        }
        
        // Refresh tables/charts
        fetchLogs();
        fetchStats();
      } else if (payload.type === 'complete') {
        setFeedState('completed');
        ws.close();
      } else if (payload.type === 'error') {
        setFeedState('error');
        setErrorMessage(payload.message);
        ws.close();
      }
    };
    
    ws.onclose = () => {
      console.log(`WebSocket closed for session ${sessId}`);
    };
    
    ws.onerror = () => {
      setFeedState('error');
      setErrorMessage("WebSocket connection error.");
    };
  };

  // Ingest stream via URL (RTSP / Webcam)
  const handleStartStream = async (urlVal: string) => {
    if (!urlVal) return;
    try {
      const formData = new FormData();
      formData.append('url', urlVal);
      
      const res = await fetch(`${API_BASE}/stream/start`, {
        method: 'POST',
        body: formData
      });
      const data = await res.json();
      connectWebSocket(data.session_id);
    } catch (err) {
      setFeedState('error');
      setErrorMessage("Failed to initialize stream feed.");
    }
  };

  // Ingest file upload (Video / Image)
  const handleFileUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    
    setIsUploading(true);
    setFeedState('idle');
    setErrorMessage(null);
    
    try {
      const formData = new FormData();
      formData.append('file', file);
      
      const res = await fetch(`${API_BASE}/upload`, {
        method: 'POST',
        body: formData
      });
      
      if (!res.ok) {
        throw new Error(await res.text());
      }
      
      const data = await res.json();
      setIsUploading(false);
      connectWebSocket(data.session_id);
    } catch (err) {
      setIsUploading(false);
      setFeedState('error');
      setErrorMessage("File upload failed. Ensure the format is supported.");
    }
  };

  // Stop active stream ingestion
  const handleStopStream = async () => {
    if (!sessionID) return;
    try {
      await fetch(`${API_BASE}/stream/stop/${sessionID}`, { method: 'POST' });
      if (wsRef.current) wsRef.current.close();
      setFeedState('idle');
      setStreamFrame(null);
      setSessionID(null);
    } catch (err) {
      console.error("Failed to cancel active stream", err);
    }
  };

  // Format Helper
  const formatTime = (isoString: string) => {
    const d = new Date(isoString);
    return d.toTimeString().split(' ')[0];
  };

  const getConfColor = (score: number) => {
    if (score > 0.85) return 'text-emerald-400';
    if (score > 0.70) return 'text-yellow-400';
    return 'text-red-400';
  };

  // Modern HSL color mapping for PieChart
  const COLORS = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899', '#71717a'];

  return (
    <div className="space-y-6">
      
      {/* SECTION 1: Live Ingestion Zone */}
      <section className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        
        {/* Left Side: The Live incoming video feed player */}
        <div className="lg:col-span-2 glass-panel rounded-xl overflow-hidden flex flex-col h-[480px]">
          <div className="bg-zinc-100 dark:bg-zinc-900 px-4 py-3 border-b border-zinc-200 dark:border-zinc-800 flex items-center justify-between">
            <div className="flex items-center space-x-2">
              <Video className="h-4 w-4 text-blue-500" />
              <span className="text-sm font-semibold tracking-wide text-zinc-700 dark:text-zinc-200">
                Live Ingestion Stream Viewport
              </span>
            </div>
            {feedState === 'streaming' && (
              <span className="flex items-center space-x-1">
                <span className="h-2 w-2 rounded-full bg-red-500 animate-ping"></span>
                <span className="text-[10px] text-red-500 uppercase tracking-widest font-bold">
                  PROCESSING
                </span>
              </span>
            )}
          </div>
          
          {/* Stream Display Frame */}
          <div className="flex-1 bg-black relative flex items-center justify-center overflow-hidden">
            {feedState === 'streaming' && streamFrame ? (
              <img 
                src={streamFrame} 
                alt="ANPR Stream feed" 
                className="w-full h-full object-contain"
              />
            ) : isUploading ? (
              <div className="text-center space-y-3">
                <RefreshCw className="h-10 w-10 text-blue-500 animate-spin mx-auto" />
                <p className="text-sm text-zinc-400">Uploading and prepping media stream...</p>
              </div>
            ) : (
              <div className="text-center space-y-4 max-w-md px-6">
                <div className="h-14 w-14 rounded-full bg-zinc-900 border border-zinc-800 flex items-center justify-center mx-auto text-zinc-500">
                  <Play className="h-6 w-6" />
                </div>
                <div>
                  <h3 className="text-sm font-medium text-white">No Stream Active</h3>
                  <p className="text-xs text-muted mt-1 leading-relaxed">
                    Select a camera source, insert an RTSP stream endpoint, or drop a video file to run the object detection models.
                  </p>
                </div>
              </div>
            )}
            
            {/* Error Banner overlay */}
            {feedState === 'error' && errorMessage && (
              <div className="absolute inset-0 bg-black/90 flex items-center justify-center p-6 text-center">
                <div className="space-y-3 max-w-sm">
                  <AlertCircle className="h-8 w-8 text-red-500 mx-auto" />
                  <h4 className="text-sm font-medium text-white">Inference Engine Error</h4>
                  <p className="text-xs text-red-400 leading-relaxed font-mono">{errorMessage}</p>
                  <button 
                    onClick={() => setFeedState('idle')}
                    className="px-3 py-1.5 rounded bg-zinc-900 border border-zinc-800 text-xs text-zinc-300 hover:bg-zinc-800 transition"
                  >
                    Dismiss
                  </button>
                </div>
              </div>
            )}
          </div>
          
          {/* Controls Bar */}
          <div className="bg-zinc-100/60 dark:bg-zinc-900/60 p-4 border-t border-zinc-200 dark:border-zinc-800 flex flex-wrap items-center gap-3">
            <div className="flex-1 min-w-[200px] flex gap-2">
              <input 
                type="text" 
                placeholder="RTSP Feed (e.g. rtsp://192.168...) or 'webcam'" 
                value={rtspUrl}
                onChange={(e) => setRtspUrl(e.target.value)}
                disabled={feedState === 'streaming'}
                className="flex-1 px-3 py-1.5 rounded bg-white dark:bg-zinc-950 border border-zinc-200 dark:border-zinc-800 text-xs text-zinc-800 dark:text-zinc-200 placeholder-zinc-400 dark:placeholder-zinc-600 focus:outline-none focus:border-blue-500"
              />
              <button
                onClick={() => handleStartStream(rtspUrl)}
                disabled={feedState === 'streaming' || !rtspUrl}
                className="px-3 py-1.5 rounded bg-blue-600 hover:bg-blue-500 disabled:bg-zinc-200 dark:disabled:bg-zinc-800 disabled:text-zinc-400 dark:disabled:text-zinc-600 text-xs font-semibold text-white transition flex items-center gap-1.5"
              >
                <Play className="h-3 w-3" /> Ingest
              </button>
            </div>
            
            <div className="h-6 w-[1px] bg-zinc-200 dark:bg-zinc-800 hidden sm:block"></div>
            
            <div className="flex items-center gap-2">
              {/* Preset buttons to help users test out-of-the-box */}
              <button
                onClick={() => { setRtspUrl('webcam'); handleStartStream('webcam'); }}
                disabled={feedState === 'streaming'}
                className="px-3 py-1.5 rounded bg-zinc-100 hover:bg-zinc-200 dark:bg-zinc-900 dark:hover:bg-zinc-800 border border-zinc-200 dark:border-zinc-800 text-xs text-zinc-700 dark:text-zinc-300 transition"
              >
                Preset Webcam
              </button>
              
              <input 
                type="file" 
                ref={fileInputRef}
                onChange={handleFileUpload}
                accept="video/*,image/*"
                className="hidden"
              />
              <button
                onClick={() => fileInputRef.current?.click()}
                disabled={feedState === 'streaming' || isUploading}
                className="px-3 py-1.5 rounded bg-zinc-100 hover:bg-zinc-200 dark:bg-zinc-900 dark:hover:bg-zinc-850 border border-zinc-200 dark:border-zinc-800 text-xs text-zinc-700 dark:text-zinc-300 transition flex items-center gap-1.5"
              >
                <Upload className="h-3 w-3" /> Upload File
              </button>
              
              {feedState === 'streaming' && (
                <button
                  onClick={handleStopStream}
                  className="px-3 py-1.5 rounded bg-red-600/20 hover:bg-red-600/30 text-red-400 border border-red-900/30 text-xs font-semibold transition flex items-center gap-1.5"
                >
                  <Square className="h-3 w-3" /> Stop
                </button>
              )}
            </div>
          </div>
        </div>
        
        {/* Right Side: Active live-feed table updating via WebSockets */}
        <div className="glass-panel rounded-xl overflow-hidden flex flex-col h-[480px]">
          <div className="bg-zinc-100 dark:bg-zinc-900 px-4 py-3 border-b border-zinc-200 dark:border-zinc-800 flex items-center justify-between">
            <span className="text-sm font-semibold tracking-wide text-zinc-700 dark:text-zinc-200">
              Live Capture Logs (WS)
            </span>
            <span className="px-2 py-0.5 rounded bg-zinc-200/55 dark:bg-zinc-950 border border-zinc-300 dark:border-zinc-850 text-[10px] text-zinc-600 dark:text-zinc-400 font-mono">
              Active Session: {liveDetections.length} log
            </span>
          </div>
          
          <div 
            ref={rightSideTableRef}
            className="flex-1 overflow-y-auto p-4 space-y-3"
          >
            {liveDetections.length === 0 ? (
              <div className="h-full flex items-center justify-center text-center p-6">
                <p className="text-xs text-zinc-500 dark:text-zinc-400 leading-relaxed">
                  Start an ingestion session. Detections will feed here programmatically as plates are read.
                </p>
              </div>
            ) : (
              liveDetections.map((det) => (
                <div 
                  key={det.id}
                  className="p-3 rounded-lg bg-white dark:bg-zinc-950 border border-zinc-200 dark:border-zinc-855 flex items-center justify-between gap-3 hover:border-blue-500/40 dark:hover:border-blue-500/30 transition-colors shadow-sm dark:shadow-none"
                >
                  <div className="flex items-center space-x-3 min-w-0">
                    {/* Crop thumbnail */}
                    <div className="h-10 w-20 rounded bg-zinc-100 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 overflow-hidden flex-shrink-0 flex items-center justify-center">
                      {det.crop_image_url ? (
                        <img 
                          src={`http://${HOSTNAME}:8000${det.crop_image_url}`} 
                          alt="Plate Crop" 
                          className="w-full h-full object-cover"
                          onError={(e) => {
                            // Suppress broken image display with placeholder
                            e.currentTarget.src = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='80' height='40'%3E%3Crect width='80' height='40' fill='%231f2937'/%3E%3C/svg%3E";
                          }}
                        />
                      ) : (
                        <span className="text-[10px] text-zinc-400 dark:text-zinc-600">No Image</span>
                      )}
                    </div>
                    
                    <div className="min-w-0">
                      <div className="text-sm font-bold font-mono text-zinc-900 dark:text-white tracking-wide truncate">
                        {det.plate_number}
                      </div>
                      <div className="text-[10px] text-zinc-500 dark:text-zinc-400 truncate mt-0.5">
                        {det.vehicle_model} • {det.vehicle_color}
                      </div>
                    </div>
                  </div>
                  
                  <div className="text-right flex-shrink-0">
                    <div className="text-[10px] text-zinc-450 dark:text-zinc-500 font-mono">
                      {formatTime(det.timestamp)}
                    </div>
                    <div className={`text-[10px] font-bold mt-0.5 font-mono ${getConfColor(det.confidence_score)}`}>
                      {(det.confidence_score * 100).toFixed(0)}%
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      </section>

      {/* SECTION 2: Analytical Overview Dashboard */}
      <section className="grid grid-cols-1 md:grid-cols-4 gap-6">
        
        {/* Core Quick stats widgets */}
        <div className="glass-panel p-5 rounded-xl space-y-2">
          <div className="flex items-center justify-between text-zinc-500 dark:text-zinc-400">
            <span className="text-xs font-semibold uppercase tracking-wider">Today's Fleet Flow</span>
            <TrendingUp className="h-4 w-4 text-blue-500" />
          </div>
          <p className="text-3xl font-extrabold tracking-tight text-zinc-900 dark:text-white">{stats.total_today}</p>
          <p className="text-[10px] text-zinc-500 dark:text-zinc-400">Unique vehicles logged last 24 hrs</p>
        </div>

        <div className="glass-panel p-5 rounded-xl space-y-2">
          <div className="flex items-center justify-between text-zinc-550 dark:text-zinc-400">
            <span className="text-xs font-semibold uppercase tracking-wider">Top Color Distribution</span>
            <Palette className="h-4 w-4 text-blue-500" />
          </div>
          <p className="text-3xl font-extrabold tracking-tight text-zinc-900 dark:text-white">
            {stats.vehicle_colors[0]?.name || "None"}
          </p>
          <p className="text-[10px] text-zinc-500 dark:text-zinc-400">
            Accounting for {stats.vehicle_colors[0] ? ((stats.vehicle_colors[0].value / (stats.total_today || 1)) * 100).toFixed(0) : 0}% of flow
          </p>
        </div>

        <div className="glass-panel p-5 rounded-xl space-y-2">
          <div className="flex items-center justify-between text-zinc-550 dark:text-zinc-400">
            <span className="text-xs font-semibold uppercase tracking-wider">Dominant Model</span>
            <Car className="h-4 w-4 text-blue-500" />
          </div>
          <p className="text-3xl font-extrabold tracking-tight text-zinc-900 dark:text-white truncate">
            {stats.vehicle_types[0]?.name || "None"}
          </p>
          <p className="text-[10px] text-zinc-500 dark:text-zinc-400">Primary logged class type today</p>
        </div>

        <div className="glass-panel p-5 rounded-xl space-y-2">
          <div className="flex items-center justify-between text-zinc-550 dark:text-zinc-400">
            <span className="text-xs font-semibold uppercase tracking-wider">System Status</span>
            <div className="h-2 w-2 rounded-full bg-emerald-500 glow-active"></div>
          </div>
          <p className="text-3xl font-extrabold tracking-tight text-zinc-900 dark:text-white">ONLINE</p>
          <p className="text-[10px] text-zinc-500 dark:text-zinc-400">FastAPI + OpenCV Workers active</p>
        </div>
      </section>

      {/* Analytics Charts Grid */}
      <section className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        
        {/* Peak Traffic Hour AreaChart */}
        <div className="lg:col-span-2 glass-panel p-6 rounded-xl flex flex-col h-[320px]">
          <h3 className="text-sm font-semibold tracking-wide text-zinc-700 dark:text-zinc-200 mb-4">
            Peak Traffic Hours (Flow Distribution)
          </h3>
          <div className="flex-1 w-full text-xs">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={stats.hourly_traffic} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                <defs>
                  <linearGradient id="colorCount" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.4}/>
                    <stop offset="95%" stopColor="#3b82f6" stopOpacity={0}/>
                  </linearGradient>
                </defs>
                <XAxis dataKey="hour" stroke="#71717a" strokeWidth={0.5} tickLine={false} />
                <YAxis stroke="#71717a" strokeWidth={0.5} tickLine={false} />
                <Tooltip 
                  contentStyle={{ backgroundColor: 'var(--tooltip-bg)', borderColor: 'var(--tooltip-border)', borderRadius: '8px' }} 
                  labelClassName="text-zinc-900 dark:text-white font-semibold font-mono"
                  itemStyle={{ color: '#3b82f6' }}
                />
                <Area type="monotone" dataKey="count" name="Vehicles" stroke="#3b82f6" strokeWidth={2} fillOpacity={1} fill="url(#colorCount)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Color PieChart distribution */}
        <div className="glass-panel p-6 rounded-xl flex flex-col h-[320px]">
          <h3 className="text-sm font-semibold tracking-wide text-zinc-700 dark:text-zinc-200 mb-4">
            Vehicle Color Segmentation
          </h3>
          <div className="flex-1 w-full flex items-center justify-center text-xs">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={stats.vehicle_colors}
                  cx="50%"
                  cy="50%"
                  innerRadius={60}
                  outerRadius={80}
                  paddingAngle={4}
                  dataKey="value"
                  label={({ name, percent }) => `${name} (${(percent * 100).toFixed(0)}%)`}
                >
                  {stats.vehicle_colors.map((_entry, index) => (
                    <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip 
                  contentStyle={{ backgroundColor: 'var(--tooltip-bg)', borderColor: 'var(--tooltip-border)', borderRadius: '8px' }} 
                  itemStyle={{ color: 'var(--tooltip-text)' }}
                />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </div>
      </section>

      {/* SECTION 3: Searchable History Table & Database Logs */}
      <section className="glass-panel rounded-xl overflow-hidden">
        <div className="bg-zinc-100 dark:bg-zinc-900 p-4 border-b border-zinc-200 dark:border-zinc-800 flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center space-x-2">
            <Search className="h-4 w-4 text-blue-500" />
            <h3 className="text-sm font-semibold tracking-wide text-zinc-700 dark:text-zinc-200">
              Historical Intelligence Database
            </h3>
          </div>
          
          <button 
            onClick={() => { fetchLogs(); fetchStats(); }}
            className="p-1.5 rounded hover:bg-zinc-200 dark:hover:bg-zinc-800 text-zinc-500 dark:text-zinc-400 hover:text-zinc-800 dark:hover:text-white transition"
          >
            <RefreshCw className="h-4 w-4" />
          </button>
        </div>

        {/* Filters bar */}
        <div className="p-4 bg-zinc-50/50 dark:bg-zinc-900/30 border-b border-zinc-200 dark:border-zinc-850 grid grid-cols-1 sm:grid-cols-2 md:grid-cols-5 gap-3">
          <input 
            type="text" 
            placeholder="Search license plate..." 
            value={searchFilter}
            onChange={(e) => { setSearchFilter(e.target.value); setPage(1); }}
            className="px-3 py-1.5 rounded bg-white dark:bg-zinc-950 border border-zinc-200 dark:border-zinc-800 text-xs text-zinc-800 dark:text-zinc-300 placeholder-zinc-400 dark:placeholder-zinc-600 focus:outline-none focus:border-blue-500"
          />
          <input 
            type="text" 
            placeholder="Filter Color (e.g. White)" 
            value={colorFilter}
            onChange={(e) => { setColorFilter(e.target.value); setPage(1); }}
            className="px-3 py-1.5 rounded bg-white dark:bg-zinc-950 border border-zinc-200 dark:border-zinc-800 text-xs text-zinc-800 dark:text-zinc-300 placeholder-zinc-400 dark:placeholder-zinc-600 focus:outline-none focus:border-blue-500"
          />
          <input 
            type="text" 
            placeholder="Filter Type (e.g. Car)" 
            value={typeFilter}
            onChange={(e) => { setTypeFilter(e.target.value); setPage(1); }}
            className="px-3 py-1.5 rounded bg-white dark:bg-zinc-950 border border-zinc-200 dark:border-zinc-800 text-xs text-zinc-800 dark:text-zinc-300 placeholder-zinc-400 dark:placeholder-zinc-600 focus:outline-none focus:border-blue-500"
          />
          <div className="flex gap-2">
            <input 
              type="date" 
              value={startDate}
              onChange={(e) => { setStartDate(e.target.value); setPage(1); }}
              className="flex-1 px-3 py-1.5 rounded bg-white dark:bg-zinc-950 border border-zinc-200 dark:border-zinc-800 text-xs text-zinc-650 dark:text-zinc-400 focus:outline-none"
            />
            <input 
              type="date" 
              value={endDate}
              onChange={(e) => { setEndDate(e.target.value); setPage(1); }}
              className="flex-1 px-3 py-1.5 rounded bg-white dark:bg-zinc-950 border border-zinc-200 dark:border-zinc-800 text-xs text-zinc-650 dark:text-zinc-400 focus:outline-none"
            />
          </div>
          
          <button
            onClick={() => {
              setSearchFilter('');
              setColorFilter('');
              setTypeFilter('');
              setStartDate('');
              setEndDate('');
              setPage(1);
            }}
            className="px-3 py-1.5 rounded bg-zinc-100 hover:bg-zinc-200 dark:bg-zinc-950 dark:hover:bg-zinc-850 border border-zinc-200 dark:border-zinc-850 text-xs text-zinc-600 hover:text-zinc-800 dark:text-zinc-400 dark:hover:text-white transition"
          >
            Reset Filters
          </button>
        </div>

        {/* Database log table */}
        <div className="overflow-x-auto w-full">
          <table className="w-full text-left text-xs border-collapse">
            <thead>
              <tr className="bg-zinc-100/50 dark:bg-zinc-900/40 border-b border-zinc-200 dark:border-zinc-850 text-zinc-600 dark:text-zinc-400 font-semibold">
                <th className="p-4">Log UUID</th>
                <th className="p-4">Trigger Timestamp</th>
                <th className="p-4">License Plate</th>
                <th className="p-4">Vehicle Model</th>
                <th className="p-4">Color</th>
                <th className="p-4">Confidence</th>
                <th className="p-4">Crop Audit</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-200 dark:divide-zinc-850 text-zinc-700 dark:text-zinc-300">
              {logs.length === 0 ? (
                <tr>
                  <td colSpan={7} className="p-8 text-center text-zinc-500 dark:text-zinc-400">
                    No matching intelligence logs found in PostgreSQL.
                  </td>
                </tr>
              ) : (
                logs.map((log) => (
                  <tr key={log.id} className="hover:bg-zinc-100/30 dark:hover:bg-zinc-900/20 transition-colors">
                    <td className="p-4 font-mono text-zinc-400 dark:text-zinc-500 text-[10px] select-all">{log.id}</td>
                    <td className="p-4 whitespace-nowrap">
                      {new Date(log.timestamp).toLocaleString()}
                    </td>
                    <td className="p-4 font-bold font-mono text-zinc-900 dark:text-white select-all text-sm tracking-wider">
                      {log.plate_number}
                    </td>
                    <td className="p-4">{log.vehicle_model || 'Unknown'}</td>
                    <td className="p-4">
                      <span className="flex items-center space-x-1.5">
                        <span 
                          className="h-2 w-2 rounded-full border border-zinc-300 dark:border-zinc-700" 
                          style={{ 
                            backgroundColor: (log.vehicle_color || '').toLowerCase() === 'white' ? '#fff' :
                                             (log.vehicle_color || '').toLowerCase() === 'black' ? '#000' :
                                             (log.vehicle_color || '').toLowerCase() === 'grey' ? '#808080' :
                                             (log.vehicle_color || '').toLowerCase() === 'silver' ? '#c0c0c0' :
                                             (log.vehicle_color || '').toLowerCase() === 'red' ? '#ef4444' :
                                             (log.vehicle_color || '').toLowerCase() === 'blue' ? '#3b82f6' : '#71717a'
                          }}
                        ></span>
                        <span>{log.vehicle_color}</span>
                      </span>
                    </td>
                    <td className={`p-4 font-bold font-mono ${getConfColor(log.confidence_score)}`}>
                      {(log.confidence_score * 100).toFixed(1)}%
                    </td>
                    <td className="p-4">
                      <div className="h-8 w-16 rounded border border-zinc-200 dark:border-zinc-800 bg-zinc-100 dark:bg-zinc-950 overflow-hidden flex items-center justify-center">
                        {log.crop_image_url ? (
                          <a 
                            href={`http://${HOSTNAME}:8000${log.crop_image_url}`} 
                            target="_blank" 
                            rel="noreferrer"
                            className="block w-full h-full"
                          >
                            <img 
                              src={`http://${HOSTNAME}:8000${log.crop_image_url}`} 
                              alt="Crop Link"
                              className="w-full h-full object-cover hover:scale-110 transition"
                              onError={(e) => {
                                e.currentTarget.src = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='80' height='40'%3E%3Crect width='80' height='40' fill='%231f2937'/%3E%3C/svg%3E";
                              }}
                            />
                          </a>
                        ) : (
                          <span className="text-[9px] text-zinc-400 dark:text-zinc-650">No Asset</span>
                        )}
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        {totalLogs > limit && (
          <div className="p-4 border-t border-zinc-200 dark:border-zinc-850 bg-zinc-50 dark:bg-zinc-900/10 flex items-center justify-between">
            <span className="text-[11px] text-zinc-500 dark:text-zinc-400">
              Showing {(page - 1) * limit + 1} - {Math.min(page * limit, totalLogs)} of {totalLogs} events
            </span>
            <div className="flex gap-2">
              <button
                disabled={page === 1}
                onClick={() => setPage(p => Math.max(1, p - 1))}
                className="px-2.5 py-1 rounded bg-zinc-100 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 disabled:opacity-40 disabled:hover:bg-zinc-100 dark:disabled:hover:bg-zinc-900 hover:bg-zinc-200 dark:hover:bg-zinc-800 text-xs transition text-zinc-700 dark:text-zinc-300"
              >
                Previous
              </button>
              <button
                disabled={page * limit >= totalLogs}
                onClick={() => setPage(p => p + 1)}
                className="px-2.5 py-1 rounded bg-zinc-100 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 disabled:opacity-40 disabled:hover:bg-zinc-100 dark:disabled:hover:bg-zinc-900 hover:bg-zinc-200 dark:hover:bg-zinc-800 text-xs transition text-zinc-700 dark:text-zinc-300"
              >
                Next
              </button>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
