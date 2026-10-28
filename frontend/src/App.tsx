import { AppProvider } from "./store/AppContext";
import { TopBar } from "./components/TopBar";
import { Sidebar } from "./components/Sidebar";
import { ChatPanel } from "./components/ChatPanel";
import { TracePanel } from "./components/TracePanel";
import { ToastContainer } from "./components/Sidebar";
import { useInit } from "./hooks/useInit";

function Inner() {
  useInit();
  return (
    <>
      <TopBar />
      <div className="workspace">
        <Sidebar />
        <ChatPanel />
        <TracePanel />
      </div>
      <ToastContainer />
    </>
  );
}

export default function App() {
  return (
    <AppProvider>
      <Inner />
    </AppProvider>
  );
}
