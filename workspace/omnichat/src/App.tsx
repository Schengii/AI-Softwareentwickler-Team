import React from 'react';
import { ChatWindow } from './components/ChatWindow';
import { WebSocketProvider } from './hooks/useWebSocket';

function App() {
  // Beispiel-Werte, in Produktion aus Auth-Context/Router
  const channelId = "general";
  const token = "dummy-jwt-token";

  return (
    <div className="flex h-screen w-screen">
      <aside className="w-[260px] bg-[#23272A] text-[#B9BBBE] p-4">
        <h2 className="text-white mb-4">OmniChat</h2>
        <ul>
          <li className="mb-2 text-white"># general</li>
          <li># random</li>
        </ul>
      </aside>
      <main className="flex-1">
        <WebSocketProvider channelId={channelId} token={token}>
          <ChatWindow />
        </WebSocketProvider>
      </main>
    </div>
  );
}

export default App;
