package com.animan.app

import android.content.ContentValues
import android.os.Environment
import android.provider.MediaStore
import android.webkit.MimeTypeMap
import java.io.File

object NativeHooks {
    private var lastNotification = 0L
    private val exportLock = Any()
    @JvmStatic fun ready() {
        EngineHost.ready = true
        EngineHost.main.post { DownloadService.finishIdle(EngineHost.context) }
    }

    @JvmStatic @Synchronized fun progress(count: Int, percent: Int, label: String): Boolean {
        val changed = count != EngineHost.activeCount
        EngineHost.activeCount = count
        EngineHost.progress = percent.coerceIn(0, 100)
        EngineHost.label = label
        val now = android.os.SystemClock.elapsedRealtime()
        if (!changed && now - lastNotification < 1000) return true
        lastNotification = now
        return DownloadService.update(EngineHost.context)
    }

    @JvmStatic fun exportFile(path: String): String = synchronized(exportLock) { exportCompletedFile(path) }

    private fun exportCompletedFile(path: String): String {
        val context = EngineHost.context
        val root = File(context.filesDir, "downloads").canonicalFile
        val source = File(path).canonicalFile
        require(source.isFile && source.path.startsWith(root.path + File.separator)) { "Invalid completed media path" }
        val preferences = context.getSharedPreferences("animan_exports", ContextMode)
        val key = source.path + ":" + source.length() + ":" + source.lastModified()
        val previous = preferences.getString(key, null)
        if (previous != null) {
            try { context.contentResolver.openFileDescriptor(android.net.Uri.parse(previous), "r")?.use { return previous } }
            catch (_: Exception) { /* User removed the shared copy; export it again. */ }
        }
        val pendingKey = "pending:" + key
        preferences.getString(pendingKey, null)?.let { pending ->
            val pendingUri = android.net.Uri.parse(pending)
            var published = false
            try {
                context.contentResolver.query(pendingUri, arrayOf(MediaStore.Downloads.IS_PENDING), null, null, null)?.use {
                    published = it.moveToFirst() && it.getInt(0) == 0
                }
                if (published) {
                    preferences.edit().putString(key, pending).remove(pendingKey).commit()
                    return pending
                }
                context.contentResolver.delete(pendingUri, null, null)
            } catch (_: Exception) { /* The previous incomplete copy was removed. */ }
            preferences.edit().remove(pendingKey).commit()
        }
        val values = ContentValues().apply {
            put(MediaStore.Downloads.DISPLAY_NAME, source.name)
            put(MediaStore.Downloads.MIME_TYPE, MimeTypeMap.getSingleton().getMimeTypeFromExtension(source.extension) ?: "video/x-matroska")
            put(MediaStore.Downloads.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS + "/Animan")
            put(MediaStore.Downloads.IS_PENDING, 1)
        }
        val resolver = context.contentResolver
        val uri = requireNotNull(resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values))
        preferences.edit().putString(pendingKey, uri.toString()).commit()
        try {
            requireNotNull(resolver.openOutputStream(uri)).use { output -> source.inputStream().use { it.copyTo(output) } }
            resolver.update(uri, ContentValues().apply { put(MediaStore.Downloads.IS_PENDING, 0) }, null, null)
            preferences.edit().putString(key, uri.toString()).remove(pendingKey).commit()
            return uri.toString()
        } catch (failure: Exception) {
            resolver.delete(uri, null, null)
            preferences.edit().remove(pendingKey).commit()
            throw failure
        }
    }
    private const val ContextMode = android.content.Context.MODE_PRIVATE
}
