import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './global.css';
import './log';   // 前端运行时日志（错误捕获并上报落盘）

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);