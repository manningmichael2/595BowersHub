/**
 * ImageGallery — displays and manages images linked to a row via a link table.
 *
 * Features:
 * - Fetches and displays thumbnails for linked images
 * - Upload via file picker or drag-and-drop
 * - Reorder via up/down arrow buttons
 * - Set primary image (star icon)
 * - Unlink image (remove link table row, not the file)
 * - Full-size preview overlay on thumbnail tap
 *
 * _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6_
 */

import { useEffect, useState, useCallback, useRef } from 'react'
import { useAuthStore } from '../../stores/auth'
import { useIsAdmin } from '../../hooks/useIsAdmin'

// ---- Types ----------------------------------------------------------------

interface ImageGalleryProps {
  schema: string
  table: string
  rowId: string
}

interface LinkedImage {
  asset_id: string
  path: string
  original_name: string | null
  mime: string
  ai_summary: string | null
  is_primary: boolean
  sort_order: number | null
}

// ---- Helpers --------------------------------------------------------------

/** Construct the full URL for serving an image from its relative path */
function imageUrl(path: string): string {
  // The API returns relative paths like "inventory/tools/abc.jpg"
  // Prepend /files/ to match the existing file serving pattern
  if (path.startsWith('/')) return path
  return `/files/${path}`
}

// ---- Component ------------------------------------------------------------

export default function ImageGallery({ schema, table, rowId }: ImageGalleryProps) {
  const isAdmin = useIsAdmin()
  const [images, setImages] = useState<LinkedImage[]>([])
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [previewImage, setPreviewImage] = useState<LinkedImage | null>(null)
  const [dragOver, setDragOver] = useState(false)
  const [confirmUnlink, setConfirmUnlink] = useState<string | null>(null)

  const fileInputRef = useRef<HTMLInputElement>(null)

  const getToken = useCallback(() => useAuthStore.getState().accessToken, [])

  const basePath = `/api/db/${schema}/${table}/rows/${rowId}/images`

  // ---- Fetch images --------------------------------------------------------

  const fetchImages = useCallback(async () => {
    setLoading(true)
    try {
      const token = getToken()
      const res = await fetch(basePath, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      })
      if (res.ok) {
        const data = await res.json()
        setImages(data)
      } else {
        setImages([])
      }
    } catch {
      setImages([])
    } finally {
      setLoading(false)
    }
  }, [basePath, getToken])

  useEffect(() => {
    fetchImages()
  }, [fetchImages])

  // ---- Upload --------------------------------------------------------------

  const uploadFile = useCallback(async (file: File) => {
    setUploading(true)
    try {
      const token = getToken()
      const formData = new FormData()
      formData.append('file', file)

      const res = await fetch(basePath, {
        method: 'POST',
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: formData,
      })

      if (res.ok) {
        await fetchImages()
      }
    } finally {
      setUploading(false)
    }
  }, [basePath, getToken, fetchImages])

  const handleFileSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (files && files.length > 0) {
      uploadFile(files[0])
    }
    // Reset input so the same file can be re-selected
    e.target.value = ''
  }, [uploadFile])

  // ---- Drag and drop upload ------------------------------------------------

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setDragOver(true)
  }, [])

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setDragOver(false)
  }, [])

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setDragOver(false)

    const files = e.dataTransfer.files
    if (files && files.length > 0) {
      uploadFile(files[0])
    }
  }, [uploadFile])

  // ---- Reorder -------------------------------------------------------------

  const reorder = useCallback(async (assetId: string, direction: 'up' | 'down') => {
    const idx = images.findIndex(img => img.asset_id === assetId)
    if (idx === -1) return

    const swapIdx = direction === 'up' ? idx - 1 : idx + 1
    if (swapIdx < 0 || swapIdx >= images.length) return

    // Build new order
    const reordered = [...images]
    const temp = reordered[idx]
    reordered[idx] = reordered[swapIdx]
    reordered[swapIdx] = temp

    // Optimistic update
    setImages(reordered)

    // Send new order to backend
    const order = reordered.map((img, i) => ({
      asset_id: img.asset_id,
      sort_order: i,
    }))

    try {
      const token = getToken()
      await fetch(`${basePath}/reorder`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ order }),
      })
    } catch {
      // Revert on failure
      await fetchImages()
    }
  }, [images, basePath, getToken, fetchImages])

  // ---- Set primary ---------------------------------------------------------

  const setPrimary = useCallback(async (assetId: string) => {
    // Optimistic update
    setImages(prev =>
      prev.map(img => ({
        ...img,
        is_primary: img.asset_id === assetId,
      }))
    )

    try {
      const token = getToken()
      const res = await fetch(`${basePath}/${assetId}/primary`, {
        method: 'PUT',
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      })
      if (!res.ok) {
        await fetchImages()
      }
    } catch {
      await fetchImages()
    }
  }, [basePath, getToken, fetchImages])

  // ---- Unlink --------------------------------------------------------------

  const unlinkImage = useCallback(async (assetId: string) => {
    try {
      const token = getToken()
      const res = await fetch(`${basePath}/${assetId}`, {
        method: 'DELETE',
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      })
      if (res.ok) {
        setImages(prev => prev.filter(img => img.asset_id !== assetId))
      }
    } catch {
      // Silently fail — image stays in gallery
    }
    setConfirmUnlink(null)
  }, [basePath, getToken])

  // ---- Render: Loading state -----------------------------------------------

  if (loading) {
    return (
      <div
        className="px-4 py-3 text-xs"
        style={{ color: 'var(--color-text-muted)' }}
      >
        Loading images…
      </div>
    )
  }

  // ---- Render: Main --------------------------------------------------------

  return (
    <div className="px-4 py-3">
      {/* Section header */}
      <div className="flex items-center gap-2 mb-2">
        <h3
          className="text-xs font-semibold uppercase tracking-wide"
          style={{ color: 'var(--color-text-muted)' }}
        >
          Photos ({images.length})
        </h3>
      </div>

      {/* Gallery area — drag-and-drop zone */}
      <div
        className="relative rounded-lg p-2 transition-colors"
        style={{
          border: `2px dashed ${dragOver ? 'var(--color-primary)' : 'var(--color-border)'}`,
          backgroundColor: dragOver ? 'color-mix(in srgb, var(--color-primary) 5%, transparent)' : 'transparent',
          minHeight: images.length === 0 ? '80px' : undefined,
        }}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
      >
        {/* Thumbnails */}
        {images.length > 0 ? (
          <div className="flex flex-wrap gap-2">
            {images.map((img, idx) => (
              <div
                key={img.asset_id}
                className="relative group rounded-md overflow-hidden"
                style={{
                  width: '80px',
                  height: '80px',
                  border: `1px solid ${img.is_primary ? 'var(--color-primary)' : 'var(--color-border)'}`,
                }}
              >
                {/* Thumbnail image */}
                <img
                  src={imageUrl(img.path)}
                  alt={img.original_name || img.ai_summary || 'Image'}
                  className="w-full h-full object-cover cursor-pointer"
                  onClick={() => setPreviewImage(img)}
                  loading="lazy"
                />

                {/* Primary star overlay */}
                {img.is_primary && (
                  <span
                    className="absolute top-0.5 left-0.5 text-xs leading-none"
                    style={{ color: 'var(--color-primary)' }}
                    title="Primary image"
                  >
                    ★
                  </span>
                )}

                {/* Action buttons — visible on hover, hidden for non-admin (Req 21.3) */}
                {isAdmin && (
                <div
                  className="absolute inset-0 flex items-end justify-center gap-0.5 pb-0.5 opacity-0 group-hover:opacity-100 transition-opacity"
                  style={{ background: 'linear-gradient(transparent 40%, rgba(0,0,0,0.6))' }}
                >
                  {/* Move up */}
                  {idx > 0 && (
                    <button
                      type="button"
                      onClick={(e) => { e.stopPropagation(); reorder(img.asset_id, 'up') }}
                      className="w-5 h-5 flex items-center justify-center rounded text-on-primary text-[10px] hover:bg-surface/20"
                      title="Move left"
                    >
                      ←
                    </button>
                  )}

                  {/* Move down */}
                  {idx < images.length - 1 && (
                    <button
                      type="button"
                      onClick={(e) => { e.stopPropagation(); reorder(img.asset_id, 'down') }}
                      className="w-5 h-5 flex items-center justify-center rounded text-on-primary text-[10px] hover:bg-surface/20"
                      title="Move right"
                    >
                      →
                    </button>
                  )}

                  {/* Set primary */}
                  {!img.is_primary && (
                    <button
                      type="button"
                      onClick={(e) => { e.stopPropagation(); setPrimary(img.asset_id) }}
                      className="w-5 h-5 flex items-center justify-center rounded text-on-primary text-[10px] hover:bg-surface/20"
                      title="Set as primary"
                    >
                      ★
                    </button>
                  )}

                  {/* Unlink */}
                  <button
                    type="button"
                    onClick={(e) => { e.stopPropagation(); setConfirmUnlink(img.asset_id) }}
                    className="w-5 h-5 flex items-center justify-center rounded text-on-primary text-[10px] hover:bg-surface/20"
                    title="Unlink image"
                  >
                    ✕
                  </button>
                </div>
                )}
              </div>
            ))}

            {/* Add button — hidden for non-admin (Req 21.3) */}
            {isAdmin && (
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              disabled={uploading}
              className="flex items-center justify-center rounded-md transition-colors"
              style={{
                width: '80px',
                height: '80px',
                border: '1px dashed var(--color-border)',
                color: 'var(--color-text-muted)',
                backgroundColor: 'var(--color-background)',
              }}
              title="Upload image"
            >
              {uploading ? (
                <span className="text-xs">…</span>
              ) : (
                <span className="text-2xl leading-none">+</span>
              )}
            </button>
            )}
          </div>
        ) : (
          /* Empty state */
          <div
            className="flex flex-col items-center justify-center h-full py-4 cursor-pointer"
            onClick={isAdmin ? () => fileInputRef.current?.click() : undefined}
            style={{ color: 'var(--color-text-muted)', cursor: isAdmin ? 'pointer' : 'default' }}
          >
            <span className="text-2xl mb-1">📷</span>
            <span className="text-xs">
              {!isAdmin ? 'No images linked' : uploading ? 'Uploading…' : 'Drop images here or click to upload'}
            </span>
          </div>
        )}
      </div>

      {/* Hidden file input */}
      <input
        ref={fileInputRef}
        type="file"
        accept="image/*"
        className="hidden"
        onChange={handleFileSelect}
      />

      {/* ---- Unlink confirmation dialog ---- */}
      {confirmUnlink && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center"
          style={{ backgroundColor: 'rgba(0,0,0,0.5)' }}
          onClick={() => setConfirmUnlink(null)}
        >
          <div
            className="rounded-lg p-4 max-w-xs w-full mx-4 shadow-xl"
            style={{
              backgroundColor: 'var(--color-surface)',
              border: '1px solid var(--color-border)',
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <p
              className="text-sm mb-3"
              style={{ color: 'var(--color-text)' }}
            >
              Unlink this image from the record? The file will not be deleted.
            </p>
            <div className="flex gap-2 justify-end">
              <button
                type="button"
                onClick={() => setConfirmUnlink(null)}
                className="text-xs px-3 py-1.5 rounded"
                style={{
                  backgroundColor: 'var(--color-background)',
                  color: 'var(--color-text)',
                  border: '1px solid var(--color-border)',
                }}
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => unlinkImage(confirmUnlink)}
                className="text-xs px-3 py-1.5 rounded font-medium"
                style={{
                  backgroundColor: 'var(--color-error)',
                  color: 'var(--color-on-primary)',
                }}
              >
                Unlink
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ---- Full-size preview overlay ---- */}
      {previewImage && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4"
          style={{ backgroundColor: 'rgba(0,0,0,0.85)' }}
          onClick={() => setPreviewImage(null)}
        >
          <div className="relative max-w-full max-h-full">
            <img
              src={imageUrl(previewImage.path)}
              alt={previewImage.original_name || previewImage.ai_summary || 'Full-size preview'}
              className="max-w-full max-h-[90vh] object-contain rounded-lg"
              onClick={(e) => e.stopPropagation()}
            />
            {/* Close button */}
            <button
              type="button"
              onClick={() => setPreviewImage(null)}
              className="absolute top-2 right-2 w-8 h-8 flex items-center justify-center rounded-full text-white text-lg bg-black/50 hover:bg-black/70 transition-colors"
              aria-label="Close preview"
            >
              ✕
            </button>
            {/* Image info */}
            {(previewImage.original_name || previewImage.ai_summary) && (
              <div
                className="absolute bottom-0 left-0 right-0 p-3 rounded-b-lg"
                style={{ background: 'linear-gradient(transparent, rgba(0,0,0,0.7))' }}
              >
                <p className="text-on-primary text-sm truncate">
                  {previewImage.original_name || previewImage.ai_summary}
                </p>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
