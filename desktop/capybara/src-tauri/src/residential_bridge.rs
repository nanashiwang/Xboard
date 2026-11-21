// One loopback listener per active asset. The public destination is fixed before
// any connection is accepted; the PX port performs the original proxy handshake.
use futures_util::{SinkExt, StreamExt};
use std::time::Duration;
use tokio::{
    io::{AsyncRead, AsyncReadExt, AsyncWrite, AsyncWriteExt},
    net::{TcpListener, TcpStream},
    task::{JoinHandle, JoinSet},
};
use tokio_tungstenite::{connect_async, tungstenite::Message, WebSocketStream};

pub struct Bridge {
    pub port: u16,
    task: JoinHandle<()>,
}

impl Drop for Bridge {
    fn drop(&mut self) {
        self.task.abort();
    }
}

impl Bridge {
    pub async fn start(url: String) -> Result<Self, String> {
        let listener = TcpListener::bind("127.0.0.1:0")
            .await
            .map_err(|_| "无法打开本机家宽连接端口")?;
        let port = listener
            .local_addr()
            .map_err(|_| "无法读取本机端口")?
            .port();
        let task = tokio::spawn(async move {
            let mut flows = JoinSet::new();
            loop {
                tokio::select! {
                    next = listener.accept(), if flows.len() < 256 => {
                        let Ok((tcp, _)) = next else { break };
                        let url = url.clone();
                        flows.spawn(async move {
                            let _ = tcp.set_nodelay(true);
                            // A reset during establishment is safe to retry. No application
                            // bytes leave the loopback socket until a handshake succeeds.
                            use tokio_tungstenite::tungstenite::{Error, error::ProtocolError};
                            for seconds in [4, 8] {
                                match tokio::time::timeout(Duration::from_secs(seconds), connect_async(&url)).await {
                                    Ok(Ok((ws, _))) => { forward(tcp, ws).await; break; }
                                    Err(_) | Ok(Err(Error::Io(_) | Error::Protocol(ProtocolError::HandshakeIncomplete))) => continue,
                                    Ok(Err(_)) => break,
                                }
                            }
                        });
                    }
                    _ = flows.join_next(), if !flows.is_empty() => {}
                }
            }
        });
        Ok(Self { port, task })
    }
}

pub(super) async fn forward<S>(tcp: TcpStream, ws: WebSocketStream<S>)
where
    S: AsyncRead + AsyncWrite + Unpin,
{
    let (mut tx, mut rx) = ws.split();
    let (mut reader, mut writer) = tcp.into_split();
    let upload = async {
        let mut buf = vec![0; 32 * 1024];
        while let Ok(n) = reader.read(&mut buf).await {
            if n == 0 || tx.send(Message::Binary(buf[..n].to_vec())).await.is_err() {
                break;
            }
        }
        let _ = tx.close().await;
    };
    let download = async {
        while let Some(Ok(frame)) = rx.next().await {
            match frame {
                Message::Binary(bytes) => {
                    if writer.write_all(&bytes).await.is_err() {
                        break;
                    }
                }
                Message::Pong(_) | Message::Ping(_) => continue,
                _ => break,
            }
        }
    };
    tokio::select! { _ = upload => {}, _ = download => {} }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    #[ignore = "requires the live stage-one ingress and active PX-1"]
    async fn stage_one_reaches_px1_authentication_without_ordinary_subscription() {
        let bridge = Bridge::start("wss://node.lumavia.fyi/residential/v1/a/20001".into())
            .await
            .unwrap();
        let mut tcp = TcpStream::connect(("127.0.0.1", bridge.port))
            .await
            .unwrap();
        tcp.write_all(&[5, 1, 2]).await.unwrap();
        let mut reply = [0; 2];
        tokio::time::timeout(Duration::from_secs(16), tcp.read_exact(&mut reply))
            .await
            .unwrap()
            .unwrap();
        assert_eq!(reply, [5, 2]);
        drop(bridge);
        assert_eq!(
            tokio::time::timeout(Duration::from_secs(2), tcp.read(&mut reply))
                .await
                .unwrap()
                .unwrap(),
            0
        );
    }
}
