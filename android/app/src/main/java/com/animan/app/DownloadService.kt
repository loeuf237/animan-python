package com.animan.app

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.IBinder
import android.os.PowerManager
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat

class DownloadService : Service() {
    private var wakeLock: PowerManager.WakeLock? = null
    override fun onBind(intent: Intent?): IBinder? = null
    override fun onCreate() {
        super.onCreate()
        instance = this
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(NotificationChannel(CHANNEL, getString(R.string.download_channel), NotificationManager.IMPORTANCE_LOW))
    }
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        // startForegroundService must be acknowledged even if the queue became
        // idle while its start request was in transit.
        showNotification()
        if (intent?.action == "pause") EngineHost.command("pause")
        if (intent?.action == "resume") EngineHost.command("resume")
        if (EngineHost.ready && EngineHost.activeCount == 0) {
            stopForeground(STOP_FOREGROUND_REMOVE)
            stopSelf()
        }
        return START_NOT_STICKY
    }
    private fun showNotification() {
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val pause = PendingIntent.getService(this, 1, Intent(this, DownloadService::class.java).setAction("pause"), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val notification = NotificationCompat.Builder(this, CHANNEL)
            .setSmallIcon(android.R.drawable.stat_sys_download).setContentTitle(getString(R.string.app_name))
            .setContentText(if (EngineHost.activeCount > 0) getString(R.string.active_downloads, EngineHost.activeCount) + " · " + EngineHost.label else getString(R.string.starting_engine))
            .setContentIntent(open).setOngoing(true).setOnlyAlertOnce(true)
            .setProgress(100, EngineHost.progress, !EngineHost.ready)
            .addAction(android.R.drawable.ic_media_pause, getString(R.string.pause_downloads), pause).build()
        startForeground(NOTIFICATION, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
        if (wakeLock == null) {
            wakeLock = (getSystemService(POWER_SERVICE) as PowerManager).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "Animan:downloads").apply {
                setReferenceCounted(false)
                acquire(6 * 60 * 60 * 1000L)
            }
        }
    }
    override fun onTimeout(startId: Int, fgsType: Int) {
        EngineHost.command("pause")
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }
    override fun onDestroy() {
        if (instance === this) instance = null
        wakeLock?.let { if (it.isHeld) it.release() }
        wakeLock = null
        super.onDestroy()
    }
    companion object {
        private const val CHANNEL = "animan-downloads"
        private const val NOTIFICATION = 1001
        @Volatile private var instance: DownloadService? = null
        fun update(context: Context): Boolean {
            if (EngineHost.ready && EngineHost.activeCount == 0) {
                EngineHost.main.post { finishIdle(context) }
                return true
            }
            instance?.let { service ->
                EngineHost.main.post { service.showNotification() }
                return true
            }
            return try {
                ContextCompat.startForegroundService(context, Intent(context, DownloadService::class.java))
                true
            } catch (failure: RuntimeException) {
                android.util.Log.w("AnimanService", "Android denied background transfer; queue will be paused", failure)
                false
            }
        }
        fun finishIdle(context: Context) {
            if (EngineHost.activeCount == 0) context.stopService(Intent(context, DownloadService::class.java))
        }
    }
}
