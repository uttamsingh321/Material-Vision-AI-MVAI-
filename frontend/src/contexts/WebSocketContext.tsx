import React, { createContext, useContext, useEffect, useRef, useState } from 'react';
import { useNotification } from './NotificationContext';

interface WebSocketContextType {
  isConnected: boolean;
  lastMessage: any;
  sendMessage: (msg: any) => void;
}

const WebSocketContext = createContext<WebSocketContextType | undefined>(undefined);

export const WebSocketProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [isConnected, setIsConnected] = useState(false);
  const [lastMessage, setLastMessage] = useState<any>(null);
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
    <WebSocketContext.Provider value={{ isConnected, lastMessage, sendMessage }}>
      {children}
    </WebSocketContext.Provider>
  );
};

export const useWebSocket = () => {
  const context = useContext(WebSocketContext);
  if (!context) throw new Error('useWebSocket must be used within WebSocketProvider');
  return context;
};
