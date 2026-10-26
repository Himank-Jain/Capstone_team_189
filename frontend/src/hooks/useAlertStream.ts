import { useEffect, useRef, useState } from 'react';

const DEFAULT_API_BASE = 'http://127.0.0.1:8001';
const MAX_RECONNECT_ATTEMPTS = 15; // Stop trying after 15 attempts
const INITIAL_RECONNECT_DELAY = 2000; // Start with 2 seconds
const HEARTBEAT_STALE_MS = 90000;

export type AlertStreamConnectionState = 'connecting' | 'connected' | 'reconnecting' | 'disconnected';

export default function useAlertStream(onMessage: (msg: unknown) => void) {
  const wsRef = useRef<WebSocket | null>(null);
  const onMessageRef = useRef(onMessage);
  const [connectionState, setConnectionState] = useState<AlertStreamConnectionState>('connecting');
  const [error, setError] = useState<string | null>(null);
  const lastHeartbeatAtRef = useRef<number | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const backoffTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    onMessageRef.current = onMessage;
  }, [onMessage]);

  useEffect(() => {
    mountedRef.current = true;
    const base = import.meta.env.VITE_API_BASE || DEFAULT_API_BASE;
    const wsUrl = base.replace(/^http/, 'ws') + '/ws/heartbeat';

    function connect() {
      if (!mountedRef.current) return;
      
      // Stop trying if max attempts reached
      if (reconnectAttemptsRef.current >= MAX_RECONNECT_ATTEMPTS) {
        setConnectionState('disconnected');
        setError('WebSocket reconnection limit reached. Check backend server.');
        return;
      }

      try {
        setConnectionState(reconnectAttemptsRef.current === 0 ? 'connecting' : 'reconnecting');
        const ws = new WebSocket(wsUrl);
        wsRef.current = ws;

        ws.onopen = () => {
          // Connection established - reset reconnect counter
          reconnectAttemptsRef.current = 0;
          setConnectionState('connected');
          setError(null);
          console.log('✓ WebSocket connected');
        };

        ws.onmessage = (event) => {
          lastHeartbeatAtRef.current = Date.now();
          setConnectionState('connected');
          try {
            const payload: unknown = JSON.parse(event.data);
            onMessageRef.current(payload);
          } catch {
            onMessageRef.current(event.data);
          }
        };

        ws.onerror = (errorEvent) => {
          console.log('WebSocket error:', errorEvent);
          if (mountedRef.current) {
            setError('WebSocket connection error');
          }
        };

        ws.onclose = () => {
          // Schedule reconnect with exponential backoff
          if (!mountedRef.current) return;

          setConnectionState('reconnecting');
          
          reconnectAttemptsRef.current += 1;
          // Exponential backoff: 2s, 4s, 8s, 16s, ... capped at 60s
          const exponentialDelay = Math.min(
            60000,
            INITIAL_RECONNECT_DELAY * Math.pow(2, Math.min(reconnectAttemptsRef.current - 1, 4))
          );
          const jitter = Math.floor(Math.random() * 1000); // 0-1s jitter
          const delay = exponentialDelay + jitter;
          
          console.log(`Reconnecting in ${delay}ms (attempt ${reconnectAttemptsRef.current})`);
          
          if (backoffTimerRef.current) clearTimeout(backoffTimerRef.current);
          backoffTimerRef.current = setTimeout(() => connect(), delay);
        };
      } catch (e) {
        console.log('WebSocket creation error:', e);
        // Retry with exponential backoff
        setConnectionState('reconnecting');
        reconnectAttemptsRef.current += 1;
        if (reconnectAttemptsRef.current < MAX_RECONNECT_ATTEMPTS) {
          const exponentialDelay = Math.min(
            60000,
            INITIAL_RECONNECT_DELAY * Math.pow(2, Math.min(reconnectAttemptsRef.current - 1, 4))
          );
          const jitter = Math.floor(Math.random() * 1000);
          const delay = exponentialDelay + jitter;
          
          if (backoffTimerRef.current) clearTimeout(backoffTimerRef.current);
          backoffTimerRef.current = setTimeout(() => connect(), delay);
        }
      }
    }

    const staleHeartbeatTimer = setInterval(() => {
      if (!mountedRef.current || lastHeartbeatAtRef.current === null) {
        return;
      }

      if (Date.now() - lastHeartbeatAtRef.current > HEARTBEAT_STALE_MS) {
        setConnectionState((current) => (current === 'disconnected' ? current : 'reconnecting'));
      }
    }, 5000);

    // Initial connection with slight delay to ensure page is ready
    const initialTimer = setTimeout(() => {
      if (mountedRef.current) {
        connect();
      }
    }, 500);

    return () => {
      mountedRef.current = false;
      clearTimeout(initialTimer);
      clearInterval(staleHeartbeatTimer);
      if (backoffTimerRef.current) clearTimeout(backoffTimerRef.current);
      if (wsRef.current) {
        wsRef.current.close();
      }
      wsRef.current = null;
    };
  }, []);

  return {
    connected: connectionState === 'connected',
    connectionState,
    error,
  };
}
