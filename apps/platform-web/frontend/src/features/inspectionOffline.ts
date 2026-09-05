import axios from "axios";

import {
  inspectionPlotKey,
  sendInspectionOutboxAction,
  type InspectionLocator,
  type InspectionOutboxAction,
  type InspectionOutboxState,
} from "@/features/inspectionField";

const DB_NAME = "dbi-inspection-pwa-v1";
const DB_VERSION = 1;
const OUTBOX_STORE = "inspection_outbox";

export type InspectionSyncResult = {
  synced: number;
  remaining: number;
  blockedState: InspectionOutboxState | null;
};

function openDatabase(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = () => {
      const database = request.result;
      if (!database.objectStoreNames.contains(OUTBOX_STORE)) {
        const store = database.createObjectStore(OUTBOX_STORE, {
          keyPath: "actionId",
        });
        store.createIndex("plotKey", "plotKey", { unique: false });
        store.createIndex("createdAt", "createdAt", { unique: false });
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error ?? new Error("IndexedDB INSPECT no disponible."));
    request.onblocked = () => reject(new Error("IndexedDB INSPECT está bloqueado por otra pestaña."));
  });
}

function transactionDone(transaction: IDBTransaction): Promise<void> {
  return new Promise((resolve, reject) => {
    transaction.oncomplete = () => resolve();
    transaction.onerror = () =>
      reject(transaction.error ?? new Error("Falló una transacción IndexedDB INSPECT."));
    transaction.onabort = () =>
      reject(transaction.error ?? new Error("Se canceló una transacción IndexedDB INSPECT."));
  });
}

function requestResult<T>(request: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error ?? new Error("Falló IndexedDB INSPECT."));
  });
}

export async function enqueueInspectionAction(
  action: InspectionOutboxAction,
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

export async function listInspectionOutbox(
  locator: InspectionLocator,
): Promise<InspectionOutboxAction[]> {
  const database = await openDatabase();
  try {
    const transaction = database.transaction(OUTBOX_STORE, "readonly");
    const request = transaction
      .objectStore(OUTBOX_STORE)
      .index("plotKey")
      .getAll(inspectionPlotKey(locator)) as IDBRequest<InspectionOutboxAction[]>;
    const result = await requestResult(request);
    await transactionDone(transaction);
    return result.sort((left, right) => left.createdAt.localeCompare(right.createdAt));
  } finally {
    database.close();
  }
}

async function replaceInspectionAction(action: InspectionOutboxAction): Promise<void> {
  const database = await openDatabase();
  try {
    const transaction = database.transaction(OUTBOX_STORE, "readwrite");
    transaction.objectStore(OUTBOX_STORE).put(action);
    await transactionDone(transaction);
  } finally {
    database.close();
  }
}

async function deleteInspectionAction(actionId: string): Promise<void> {
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
  state: InspectionOutboxState;
  message: string;
} {
  if (!axios.isAxiosError(error) || !error.response) {
    return {
      state: "pending",
      message: "Sin conexión; la observación continúa pendiente.",
    };
  }

  const status = error.response.status;
  if (status === 401 || status === 403) {
    return {
      state: "auth_required",
      message: "La sesión actual debe volver a autorizar esta observación.",
    };
  }
  if (status === 409) {
    return {
      state: "conflict",
      message: "El servidor detectó una identidad o contenido divergente; requiere revisión.",
    };
  }
  return {
    state: "failed",
    message: `La sincronización INSPECT falló con HTTP ${status}.`,
  };
}

export async function syncInspectionOutbox(
  locator: InspectionLocator,
): Promise<InspectionSyncResult> {
  const actions = await listInspectionOutbox(locator);
  let synced = 0;
  let blockedState: InspectionOutboxState | null = null;

  for (const action of actions) {
    if (action.state === "conflict") {
      blockedState = "conflict";
      break;
    }

    const syncingAction: InspectionOutboxAction = {
      ...action,
      state: "syncing",
      attemptCount: action.attemptCount + 1,
      updatedAt: new Date().toISOString(),
      lastError: null,
    };
    await replaceInspectionAction(syncingAction);

    try {
      await sendInspectionOutboxAction(syncingAction);
      await deleteInspectionAction(syncingAction.actionId);
      synced += 1;
    } catch (error) {
      const failure = syncFailure(error);
      await replaceInspectionAction({
        ...syncingAction,
        state: failure.state,
        updatedAt: new Date().toISOString(),
        lastError: failure.message,
      });
      blockedState = failure.state;
      break;
    }
  }

  const remaining = (await listInspectionOutbox(locator)).length;
  return { synced, remaining, blockedState };
}

export function clearInspectionOfflineData(): Promise<void> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.deleteDatabase(DB_NAME);
    request.onsuccess = () => resolve();
    request.onerror = () => reject(request.error ?? new Error("No se pudo borrar IndexedDB INSPECT."));
    request.onblocked = () => resolve();
  });
}
