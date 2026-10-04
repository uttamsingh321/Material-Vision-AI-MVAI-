import React, { createContext, useContext, useEffect, useRef, useState } from 'react';
import { useNotification } from './NotificationContext';

interface WebSocketContextType {
  isConnected: boolean;
  lastMessage: any;
  sendMessage: (msg: any) => void;
  foundCount: number;
  notFoundCount: number;
  logs: string[];
}

const WebSocketContext = createContext<WebSocketContextType | undefined>(undefined);

export const WebSocketProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [isConnected, setIsConnected] = useState(false);
  const [lastMessage, setLastMessage] = useState<any>(null);
  const [foundCount, setFoundCount] = useState(0);
  const [notFoundCount, setNotFoundCount] = useState(0);
  const [logs, setLogs] = useState<string[]>([]);
  const wsRef = useRef<WebSocket | null>(null);
  const { addNotification } = useNotification();
  const reconnectTimeout = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const reconnectAttempts = useRef(0);

  useEffect(() => {
    let intentionallyClosed = false;

    const connect = () => {
      if (reconnectAttempts.current > 3) {
        console.warn('WebSocket reconnect limit reached. Disabling auto-reconnect.');
        return;
      }

      const wsUrl = import.meta.env.VITE_WS_URL || 'ws://localhost:8001/ws';
      const ws = new WebSocket(wsUrl);

      ws.onopen = () => {
        setIsConnected(true);
        reconnectAttempts.current = 0;
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          setLastMessage(data);
          
          if (data.type === 'log') {
            const logData = data.data;
            setLogs(prev => [...prev.slice(-49), logData]);
            if (logData.includes('] Found:') || logData.includes('] Cached:')) {
              setFoundCount(c => c + 1);
            } else if (logData.includes('] No images found') || logData.includes('] Error')) {
              setNotFoundCount(c => c + 1);
            }
          }
        } catch (e) {
          console.error('Failed to parse WS message');
        }
      };

      ws.onclose = () => {
        setIsConnected(false);
        if (!intentionallyClosed) {
          reconnectAttempts.current += 1;
          reconnectTimeout.current = setTimeout(connect, Math.min(3000 * reconnectAttempts.current, 10000));
        }
      };

      ws.onerror = () => {
        ws.close();
      };

      wsRef.current = ws;
    };

    connect();

    return () => {
      intentionallyClosed = true;
      if (reconnectTimeout.current) clearTimeout(reconnectTimeout.current);
      wsRef.current?.close();
    };
  }, []);

  const sendMessage = (msg: any) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(msg));
    }
  };

  return (
    <WebSocketContext.Provider value={{ isConnected, lastMessage, sendMessage, foundCount, notFoundCount, logs }}>
      {children}
    </WebSocketContext.Provider>
  );
};

export const useWebSocket = () => {
  const context = useContext(WebSocketContext);
  if (!context) throw new Error('useWebSocket must be used within WebSocketProvider');
  return context;
};
