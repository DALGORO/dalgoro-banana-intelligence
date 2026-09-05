import axios from "axios";

import {
  getSamplingPlan,
  samplingPlanKey,
  sendSamplingOutboxAction,
  type SamplingOutboxAction,
  type SamplingOutboxState,
  type SamplingPlan,
  type SamplingPlanLocator,
} from "@/features/samplingField";

const DB_NAME = "dbi-field-pwa-v1";
const DB_VERSION = 1;
const PLAN_STORE = "sampling_plans";
const OUTBOX_STORE = "sampling_outbox";

export type CachedSamplingPlan = {
  key: string;
  locator: SamplingPlanLocator;
  plan: SamplingPlan;
  cachedAt: string;
};

export type SamplingSyncResult = {
  synced: number;
  remaining: number;
  blockedState: SamplingOutboxState | null;
};

function openDatabase(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);

    request.onupgradeneeded = () => {
      const database = request.result;
      if (!database.objectStoreNames.contains(PLAN_STORE)) {
        database.createObjectStore(PLAN_STORE, { keyPath: "key" });
      }
      if (!database.objectStoreNames.contains(OUTBOX_STORE)) {
        const outbox = database.createObjectStore(OUTBOX_STORE, {
          keyPath: "actionId",
        });
        outbox.createIndex("planKey", "planKey", { unique: false });
        outbox.createIndex("createdAt", "createdAt", { unique: false });
      }
    };

    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error ?? new Error("IndexedDB no disponible."));
    request.onblocked = () => reject(new Error("IndexedDB está bloqueado por otra pestaña."));
  });
}

function transactionDone(transaction: IDBTransaction): Promise<void> {
  return new Promise((resolve, reject) => {
    transaction.oncomplete = () => resolve();
    transaction.onerror = () =>
      reject(transaction.error ?? new Error("Falló una transacción IndexedDB."));
    transaction.onabort = () =>
      reject(transaction.error ?? new Error("Se canceló una transacción IndexedDB."));
  });
}

function requestResult<T>(request: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error ?? new Error("Falló IndexedDB."));
  });
}

export async function cacheSamplingPlan(
  locator: SamplingPlanLocator,
  plan: SamplingPlan,
): Promise<void> {
  const database = await openDatabase();
  try {
    const transaction = database.transaction(PLAN_STORE, "readwrite");
    transaction.objectStore(PLAN_STORE).put({
      key: samplingPlanKey(locator),
      locator,
      plan,
      cachedAt: new Date().toISOString(),
    } satisfies CachedSamplingPlan);
    await transactionDone(transaction);
  } finally {
    database.close();
  }
}

export async function getCachedSamplingPlan(
  locator: SamplingPlanLocator,
): Promise<CachedSamplingPlan | null> {
  const database = await openDatabase();
  try {
    const transaction = database.transaction(PLAN_STORE, "readonly");
    const request = transaction
      .objectStore(PLAN_STORE)
      .get(samplingPlanKey(locator)) as IDBRequest<CachedSamplingPlan | undefined>;
    const result = await requestResult(request);
    await transactionDone(transaction);
    return result ?? null;
  } finally {
    database.close();
  }
}

export async function enqueueSamplingAction(
  action: SamplingOutboxAction,
): Promise<void> {
  const database = await openDatabase();
  try {
    const transaction = database.transaction(OUTBOX_STORE, "readwrite");
    transaction.objectStore(OUTBOX_STORE).put(action);
    await transactionDone(transaction);
  } finally {
    database.close();
  }
}

export async function listSamplingOutbox(
  locator: SamplingPlanLocator,
): Promise<SamplingOutboxAction[]> {
  const database = await openDatabase();
  try {
    const transaction = database.transaction(OUTBOX_STORE, "readonly");
    const index = transaction.objectStore(OUTBOX_STORE).index("planKey");
    const request = index.getAll(
      samplingPlanKey(locator),
    ) as IDBRequest<SamplingOutboxAction[]>;
    const result = await requestResult(request);
    await transactionDone(transaction);
    return result.sort((left, right) => left.createdAt.localeCompare(right.createdAt));
  } finally {
    database.close();
  }
}

async function replaceSamplingAction(action: SamplingOutboxAction): Promise<void> {
  const database = await openDatabase();
  try {
    const transaction = database.transaction(OUTBOX_STORE, "readwrite");
    transaction.objectStore(OUTBOX_STORE).put(action);
    await transactionDone(transaction);
  } finally {
    database.close();
  }
}

async function deleteSamplingAction(actionId: string): Promise<void> {
  const database = await openDatabase();
  try {
    const transaction = database.transaction(OUTBOX_STORE, "readwrite");
    transaction.objectStore(OUTBOX_STORE).delete(actionId);
    await transactionDone(transaction);
  } finally {
    database.close();
  }
}

function syncFailure(error: unknown): {
  state: SamplingOutboxState;
  message: string;
} {
  if (!axios.isAxiosError(error) || !error.response) {
    return {
      state: "pending",
      message: "Sin conexión; la acción continúa pendiente.",
    };
  }

  const status = error.response.status;
  if (status === 401 || status === 403) {
    return {
      state: "auth_required",
      message: "La sesión actual debe volver a autorizar esta acción.",
    };
  }
  if (status === 409) {
    return {
      state: "conflict",
      message: "El servidor reportó un conflicto; requiere revisión explícita.",
    };
  }
  return {
    state: "failed",
    message: `La sincronización falló con HTTP ${status}.`,
  };
}

export async function syncSamplingOutbox(
  locator: SamplingPlanLocator,
): Promise<SamplingSyncResult> {
  const actions = await listSamplingOutbox(locator);
  let synced = 0;
  let blockedState: SamplingOutboxState | null = null;

  for (const action of actions) {
    if (action.state === "conflict") {
      blockedState = "conflict";
      break;
    }

    const syncingAction: SamplingOutboxAction = {
      ...action,
      state: "syncing",
      attemptCount: action.attemptCount + 1,
      updatedAt: new Date().toISOString(),
      lastError: null,
    };
    await replaceSamplingAction(syncingAction);

    try {
      await sendSamplingOutboxAction(syncingAction);
      await deleteSamplingAction(syncingAction.actionId);
      synced += 1;
    } catch (error) {
      const failure = syncFailure(error);
      await replaceSamplingAction({
        ...syncingAction,
        state: failure.state,
        updatedAt: new Date().toISOString(),
        lastError: failure.message,
      });
      blockedState = failure.state;
      break;
    }
  }

  const remaining = (await listSamplingOutbox(locator)).length;
  return { synced, remaining, blockedState };
}

export async function refreshAndCacheSamplingPlan(
  locator: SamplingPlanLocator,
): Promise<SamplingPlan> {
  const plan = await getSamplingPlan(locator);
  await cacheSamplingPlan(locator, plan);
  return plan;
}

export function clearDbiOfflineData(): Promise<void> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.deleteDatabase(DB_NAME);
    request.onsuccess = () => resolve();
    request.onerror = () => reject(request.error ?? new Error("No se pudo borrar IndexedDB."));
    request.onblocked = () => resolve();
  });
}
