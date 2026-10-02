package io.github.iffix.neutrino

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
import io.github.iffix.neutrino.words.WordCatalog
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.launch

/**
 * The foreground service the app core runs in while any hub is bound: the hub channels, the
 * share connections and the loopback forwards keep running when the app leaves the screen. Its
 * one notification names how many hubs are connected; it stops itself once the last hub is
 * left, and every forward stops with it.
 */
class ClientCoreService : Service() {
    private var watch: Job? = null

    private val app: NeutrinoApplication
        get() = application as NeutrinoApplication

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val type = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE
        } else {
            0
        }
        val count = ClientCoreHold.connectedCount(app.hubs.value)
        ServiceCompat.startForeground(this, CLIENT_CORE_NOTIFICATION_ID, notification(count), type)
        if (watch == null) {
            watch = app.scope.launch {
                combine(app.bindingStore.bindings, app.hubs) { bindings, hubs ->
                    bindings.isNotEmpty() to ClientCoreHold.connectedCount(hubs)
                }.distinctUntilChanged().collect { (isHeld, connected) ->
                    if (isHeld) {
                        getSystemService(NotificationManager::class.java)
                            .notify(CLIENT_CORE_NOTIFICATION_ID, notification(connected))
                    } else {
                        stopSelf()
                    }
                }
            }
        }
        return START_STICKY
    }

    override fun onDestroy() {
        watch?.cancel()
        watch = null
        app.portForwards.stopAll()
        ServiceCompat.stopForeground(this, ServiceCompat.STOP_FOREGROUND_REMOVE)
        super.onDestroy()
    }

    private fun notification(count: Int): Notification {
        val words = WordCatalog.load(assets, app.settingsStore.settings.value.language)
        getSystemService(NotificationManager::class.java).createNotificationChannel(
            NotificationChannel(
                CLIENT_CORE_NOTIFICATION_CHANNEL,
                words.word("ui.core_channel"),
                NotificationManager.IMPORTANCE_LOW,
            ),
        )
        val open = PendingIntent.getActivity(
            this,
            0,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE,
        )
        return NotificationCompat.Builder(this, CLIENT_CORE_NOTIFICATION_CHANNEL)
            .setSmallIcon(R.drawable.ic_launcher_monochrome)
            .setContentTitle(words.word("ui.core_notice", mapOf("count" to count)))
            .setContentIntent(open)
            .setOngoing(true)
            .build()
    }
}
