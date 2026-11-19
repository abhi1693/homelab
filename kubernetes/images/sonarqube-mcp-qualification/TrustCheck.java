import java.security.MessageDigest;
import java.security.KeyStore;
import java.security.cert.X509Certificate;
import java.util.HexFormat;
import javax.net.ssl.TrustManagerFactory;
import javax.net.ssl.X509TrustManager;

public class TrustCheck {
    public static void main(String[] denied) throws Exception {
        var runtime = Runtime.version();
        if (runtime.feature() != 21 || runtime.compareTo(Runtime.Version.parse("21.0.13")) < 0) {
            throw new IllegalStateException("Unqualified JVM version: " + runtime);
        }
        System.out.println("Java " + runtime);
        var factory = TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm());
        factory.init((KeyStore) null);
        int count = 0;
        for (var manager : factory.getTrustManagers()) {
            if (!(manager instanceof X509TrustManager)) continue;
            for (X509Certificate cert : ((X509TrustManager) manager).getAcceptedIssuers()) {
                count++;
                String hash = HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(cert.getEncoded()));
                for (String blocked : denied) {
                    if (hash.equalsIgnoreCase(blocked)) throw new IllegalStateException("Distrusted CA remains trusted: " + hash);
                }
            }
        }
        if (count == 0) throw new IllegalStateException("Empty default JVM trust store");
        System.out.println("PASS: default JVM trust managers loaded " + count + " roots; distrusted fingerprints absent");
    }
}
