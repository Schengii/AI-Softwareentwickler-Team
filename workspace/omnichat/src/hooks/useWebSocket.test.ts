import { renderHook, act } from '@testing-library/react';
import { vi, describe, it, expect, beforeEach, afterEach } from 'vitest';
import { WebSocketProvider, useWebSocket } from './useWebSocket';
import React from 'react';

describe('useWebSocket Hook', () => {
  let mockWebSocket: any;

  beforeEach(() => {
    mockWebSocket = {
      send: vi.fn(),
      close: vi.fn(),
      readyState: WebSocket.OPEN,
    };
    // Mock global WebSocket
    global.WebSocket = vi.fn().mockImplementation(() => mockWebSocket) as any;
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('should connect to the correct URL', () => {
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <WebSocketProvider channelId="123" token="abc">{children}</WebSocketProvider>
    );
    renderHook(() => useWebSocket(), { wrapper });
    expect(global.WebSocket).toHaveBeenCalledWith('ws://localhost:8000/ws/123?token=abc');
  });

  it('should send messages when connected', () => {
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <WebSocketProvider channelId="123" token="abc">{children}</WebSocketProvider>
    );
    const { result } = renderHook(() => useWebSocket(), { wrapper });
    
    // Simulate connection open
    act(() => {
      mockWebSocket.onopen();
    });

    act(() => {
      result.current.sendMessage('hello');
    });

    expect(mockWebSocket.send).toHaveBeenCalledWith(JSON.stringify({ content: 'hello' }));
  });
});
