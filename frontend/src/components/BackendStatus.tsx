import { useEffect, useState } from 'react';
import { readHealth } from '../health';

export function BackendStatus() {
  const [state, setState] = useState<'loading' | 'available' | 'unavailable'>('loading');
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setState('loading');
    readHealth(controller.signal).then(() => {
      if (!controller.signal.aborted) setState('available');
    }).catch(() => {
      if (!controller.signal.aborted) setState('unavailable');
    });
    return () => controller.abort();
  }, [attempt]);

  return (
    <div className="backend-status" data-state={state}>
      <span role="status">{state === 'loading' ? 'Checking backend' : state === 'available' ? 'Backend reachable' : 'Backend unavailable'}</span>
      {state === 'unavailable' ? <button type="button" onClick={() => setAttempt((value) => value + 1)}>Retry health check</button> : null}
    </div>
  );
}
