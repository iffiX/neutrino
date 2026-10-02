package io.github.iffix.neutrino.forward

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import io.github.iffix.neutrino.FORWARD_NOTIFICATION_CHANNEL
import io.github.iffix.neutrino.FORWARD_NOTIFICATION_ID
import io.github.iffix.neutrino.FORWARD_SERVICE_ACTION_STOP
import io.github.iffix.neutrino.MainActivity
import io.github.iffix.neutrino.NeutrinoApplication
import io.github.iffix.neutrino.R
import io.github.iffix.neutrino.words.WordCatalog
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch

/**
 * The started service that keeps the process, and with it the loopback forwards, alive while
 * any forward listens: a notification names how many, and its Stop ends every one. It is apart
 * from the VPN service and stops itself once no forward is left.
 */
class PortForwardService : Service() {
    private var watch: Job? = null

    private val app: NeutrinoApplication
        get() = application as NeutrinoApplication

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val count = app.portForwards.rows.value.values.count { it.isForwarded }
        val type = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE
        } else {
            0
        }
        ServiceCompat.startForeground(this, FORWARD_NOTIFICATION_ID, notification(count), type)
        if (intent?.action == FORWARD_SERVICE_ACTION_STOP) app.portForwards.stopAll()
        if (watch == null) {
            watch = app.scope.launch {
                app.portForwards.rows.collect { rows ->
                    val forwarded = rows.values.count { it.isForwarded }
                    if (forwarded == 0) {
                        stopSelf()
                    } else {
                        getSystemService(NotificationManager::class.java)
                            .notify(FORWARD_NOTIFICATION_ID, notification(forwarded))
                    }
                }
            }
        }
        return START_NOT_STICKY
    }

    override fun onDestroy() {
        watch?.cancel()
        watch = null
        ServiceCompat.stopForeground(this, ServiceCompat.STOP_FOREGROUND_REMOVE)
        super.onDestroy()
    }

    private fun notification(count: Int): Notification {
        val words = WordCatalog.load(assets, app.settingsStore.settings.value.language)
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(
            NotificationChannel(
                FORWARD_NOTIFICATION_CHANNEL,
                words.word("ui.forward_channel"),
                NotificationManager.IMPORTANCE_LOW,
            ),
        )
        val open = PendingIntent.getActivity(
            this,
            0,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE,
        )
        val stop = PendingIntent.getService(
            this,
            0,
            Intent(this, PortForwardService::class.java).setAction(FORWARD_SERVICE_ACTION_STOP),
            PendingIntent.FLAG_IMMUTABLE,
        )
        return NotificationCompat.Builder(this, FORWARD_NOTIFICATION_CHANNEL)
            .setSmallIcon(R.drawable.ic_launcher_monochrome)
            .setContentTitle(words.word("ui.forward_notice", mapOf("count" to count)))
            .setContentIntent(open)
            .setOngoing(true)
            .addAction(0, words.word("ui.forward_stop"), stop)
            .build()
    }
}
