import { io, Socket } from 'socket.io-client'
import { getAccessToken } from './api'

const WS_URL = import.meta.env.VITE_WS_URL ?? 'http://localhost:8000'

let socket: Socket | null = null

export function getSocket(): Socket {
  if (!socket) {
    socket = io(WS_URL, {
      path: '/ws',
      transports: ['websocket', 'polling'],
      autoConnect: false,
      reconnection: true,
      reconnectionAttempts: 10,
      reconnectionDelay: 1000,
      auth: (cb) => cb({ token: getAccessToken() }),
    })

    socket.on('connect', () => {
      console.log('[WS] Connected:', socket?.id)
    })

    socket.on('disconnect', (reason) => {
      console.log('[WS] Disconnected:', reason)
    })

    socket.on('connect_error', (err) => {
      console.warn('[WS] Connection error:', err.message)
    })
  }
  return socket
}

export function connectSocket(learnerId?: string) {
  const s = getSocket()
  if (!s.connected && getAccessToken()) {
    s.connect()
    if (learnerId) {
      s.once('connect', () => {
        s.emit('join_room', { learner_id: learnerId })
      })
    }
  }
  return s
}

export function disconnectSocket() {
  if (socket?.connected) {
    socket.disconnect()
  }
}

// Typed event names matching backend exactly
export const WS_EVENTS = {
  AGENT_STATUS: 'agent:status',
  CURRICULUM_UPDATE: 'curriculum:update',
  QUIZ_READY: 'quiz:ready',
  PROGRESS_UPDATE: 'progress:update',
  DOUBT_STREAM: 'doubt:stream',
} as const
