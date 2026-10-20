/**
 * The move action: a `sidebar.workspaces.session.menu.item` row that raises
 * the move request, and the `shell.overlay` dialog entry that answers it. The
 * dialog lives outside the row menu because the row unmounts with the menu.
 *
 * A move is an account change, not a relocation: the Session's log and its own
 * working directory stay where they are, so the dialog only offers the
 * Workspaces that could own it besides the one it already sits in, and an
 * unknown or refused target keeps the dialog open with the Host's message.
 */
import { useState } from 'react'
import { Button, IconFolderOpenOutlineRegular, MenuItemButton, Modal } from '@deepseek-ai/dsh-client-ui-primitives'
import { workspaceDisplayTitle } from '@deepseek-ai/dsh-api-workspace-controller/default-workspace'
import type { WorkspaceId, WorkspaceView } from '@deepseek-ai/dsh-api-workspace-controller/client'
import type {
  MoveSessionInjected, SessionMenuItemProps, SessionMoveDialogInjected, SessionMoveDialogProps, SessionMoveTarget,
} from '../contract/slots.ts'
import css from '../rows/WorkspaceBrowser.module.css'

/**
 * Menu row (order 350): ask for the move dialog, between fork and archive.
 * @param props - owner share, menu open state, and the move share.
 * @returns the row.
 */
export function MoveSessionMenuItem({
  sessionId, displayTitle, useMenuOpenState, requestSessionMove, t,
}: SessionMenuItemProps<MoveSessionInjected>) {
  const [, setMenuOpen] = useMenuOpenState()
  return (
    <MenuItemButton
      icon={<IconFolderOpenOutlineRegular />}
      onSelect={() => {
        setMenuOpen(false)
        requestSessionMove(sessionId, displayTitle)
      }}
    >
      {t('move.menu')}
    </MenuItemButton>
  )
}

/**
 * The `shell.overlay` entry: nothing while no move is requested, otherwise one
 * dialog per request (keyed by the Session, so a new request starts fresh).
 * @param props - the request hook, the Workspace rows, their settlement, the move hop, and the locale seat.
 * @returns the open dialog, or null.
 */
export function SessionMoveDialog({
  useMoveRequest, useWorkspaceRows, settleSessionMove, moveSession, t,
}: SessionMoveDialogProps) {
  const request = useMoveRequest(pending => pending)
  if (request === null) return null
  return (
    <MoveForm
      key={request.sessionId}
      request={request}
      workspaces={useWorkspaceRows(items => items)}
      moveSession={moveSession}
      onSettle={settleSessionMove}
      t={t}
    />
  )
}

/** One request's dialog: the in-flight and error state die with it. */
function MoveForm({ request, workspaces, moveSession, onSettle, t }: {
  request: SessionMoveTarget
  workspaces: readonly WorkspaceView[]
  moveSession: SessionMoveDialogInjected['moveSession']
  onSettle: () => void
  t: SessionMoveDialogProps['t']
}) {
  // The Workspace that already owns the row is not a destination; with no
  // other Workspace there is nothing to offer, so the entry says so instead of
  // showing an empty list.
  const targets = workspaces.filter(workspace => !workspace.sessionIds.includes(request.sessionId))
  const [moving, setMoving] = useState<WorkspaceId | null>(null)
  const [error, setError] = useState<string | null>(null)
  const close = () => {
    if (moving !== null) return
    onSettle()
  }
  const confirm = (workspaceId: WorkspaceId) => {
    if (moving !== null) return
    setMoving(workspaceId)
    setError(null)
    moveSession(request.sessionId, workspaceId).then(() => {
      setMoving(null)
      onSettle()
    }).catch((reason: unknown) => {
      setMoving(null)
      setError(reason instanceof Error ? reason.message : String(reason))
    })
  }
  return (
    <Modal
      open
      onClose={close}
      closeLabel={t('close')}
      title={t('move.dialog.title')}
      description={t('move.dialog.desc')}
      footer={<Button variant="outline" disabled={moving !== null} onClick={close}>{t('cancel')}</Button>}
    >
      {targets.length === 0
        ? <div className={css.moveError}>{t('move.dialog.empty')}</div>
        : (
          <div className={css.moveTargetList}>
            {targets.map(workspace => (
              <button
                key={workspace.workspaceId}
                type="button"
                className={css.moveTargetButton}
                disabled={moving !== null}
                data-modal-autofocus={workspace.workspaceId === targets[0]?.workspaceId ? '' : undefined}
                onClick={() => { confirm(workspace.workspaceId) }}
              >
                <span>{workspaceDisplayTitle(workspace.title, t('workspace.defaultName'))}</span>
                <span className={css.moveTargetPath}>{workspace.path}</span>
              </button>
            ))}
          </div>
        )}
      {error !== null && <div className={css.moveError} role="alert">{error}</div>}
    </Modal>
  )
}
