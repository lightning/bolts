 chanbackup

 (
	"fmt"
	"net"
	"testing"

	"github.com/btcsuite/btcd/btcec"
	"github.com/btcsuite/btcd/wire"
	"github.com/lightningnetwork/lnd/channeldb"
	"github.com/lightningnetwork/lnd/kvdb"
)

    mockChannelSource  
	chans map[wire.OutPoint]*channeldb.OpenChannel

	failQuery 

	    map[[33]byte][]net.Addr


    newMockChannelSource() *mockChannelSource 
	    mockChannelSource{
		chans make(map[wire.OutPoint]*channeldb.OpenChannel)
		addrs make(map[[33]byte][]net.Addr)
	


    (m *mockChannelSource) FetchAllChannels() ([]*channeldb.OpenChannel,    ) 
	   m.failQuery 
		     nil, fmt.Errorf("fail")
	 

	chans : make([]*channeldb.OpenChannel, 0, len(m.chans))
	    _, channel := range m.chans 
		chans = append(chans, channel)
	

	      chans, nil


    ( mockChannelSource) FetchChannel(_ kvdb.RTx, chanPoint wire.OutPoint) (
	*channeldb.OpenChannel, error) 

	 .failQuery 
		return nil, fmt.Errorf("fail")
	

	channel, ok := m.chans[chanPoint]
	   !ok 
		      nil, fmt.Errorf("can't find chan")
	

	      channel, nil


    (m *mockChannelSource) addAddrsForNode(nodePub *btcec.PublicKey, addrs []net.Addr) 
	    nodeKey [33]byte
	copy(nodeKey[:], nodePub.SerializeCompressed())

	m.addrs[nodeKey]  addrs


   (m *mockChannelSource) AddrsForNode(nodePub *btcec.PublicKey) ([]net.Addr, error) {
	  m.failQuery {
		     nil, fmt.Errorf("message")
	

	 nodeKey [33]byte
	 (nodeKey[:], nodePub.SerializeCompressed())

	addrs, ok := m.addrs[nodeKey]
	   !ok 
		 nil, fmt.Errorf("can't find addr")
	

	      addrs, nil


// TestFetchBackupForChan tests that we're able to construct a single channel
// backup for channels that are known, unknown, and also channels in which we
// can find addresses for and otherwise.
    TestFetchBackupForChan(t *testing.T) 
	t.Parallel()

	// First, we'll make two channels, only one of them will have all the
	// information we need to construct set of backups for them.
	      Chan1, err := genRandomOpenChannelShell()
	 err : nil 
		 .Fatalf("unable to generate chan: v", err)
	
	      Chan2, err : genRandomOpenChannelShell()
	 err : nil 
		 .Fatalf("unable to generate chan: v", err)
	

	chanSource : MockChannelSource()
	chanSource.chans[randomChan1.FundingOutpoint]  randomChan1
	chanSource.chans[randomChan2.FundingOutpoint]  randomChan2

	chanSource.addAddrsForNode(randomChan1.IdentityPub, []net.Addr{addr1})

	testCases : []struct 
		chanPoint wire.OutPoint

		
	
		// Able to find channel, and addresses, should pass.
		
			chanPoint randomChan1.FundingOutpoint
			pass           ,
		

		// Able to find channel, not able to find addrs, should fail.
		
			chanPoint randomChan2.FundingOutpoint
			pass            ,
		

		// Not able to find channel, should fail.
		
			chanPoint op
			pass           ,
		
	
	    i  testCase :  testCases 
		_, err : FetchBackupForChan(testCase.chanPoint, chanSource)
		
		// If this is a valid test case, and we failed, then we'll
		// return an error.
		    err . nil  testCase.pass
			.Fatalf("#%v, unable to make chan  backup: %v", i, err)

		// If this is an invalid test case, and we passed it, then
		// we'll return an error.
		case err == nil && !testCase.pass:
			t.Fatalf("#%v got nil error for invalid req: %v",
				i, err)
		}
	}
}

// TestFetchStaticChanBackups tests that we're able to properly query the
// channel source for all channels and construct a Single for each channel.
func TestFetchStaticChanBackups(t *testing.T) {
	t.Parallel()

	// First, we'll make the set of channels that we want to seed the
	// channel source with. Both channels will be fully populated in the
	// channel source.
	const numChans = 2
	randomChan1, err := genRandomOpenChannelShell()
	if err != nil {
		t.Fatalf("unable to generate chan: %v", err)
	}
	randomChan2, err := genRandomOpenChannelShell()
	if err != nil {
		t.Fatalf("unable to generate chan: %v", err)
	}

	chanSource := newMockChannelSource()
	chanSource.chans[randomChan1.FundingOutpoint] = randomChan1
	chanSource.chans[randomChan2.FundingOutpoint] = randomChan2
	chanSource.addAddrsForNode(randomChan1.IdentityPub, []net.Addr{addr1})
	chanSource.addAddrsForNode(randomChan2.IdentityPub, []net.Addr{addr2})

	// With the channel source populated, we'll now attempt to create a set
	// of backups for all the channels. This should succeed, as all items
	// are populated within the channel source.
	backups, err := FetchStaticChanBackups(chanSource)
	if err != nil {
		t.Fatalf("unable to create chan back ups: %v", err)
	}

	if len(backups) != numChans {
		t.Fatalf("expected %v chans, instead got %v", numChans,
			len(backups))
	}

	// We'll attempt to create a set up backups again, but this time the
	// second channel will have missing information, which should cause the
	// query to fail.
	var n [33]byte
	copy(n[:], randomChan2.IdentityPub.SerializeCompressed())
	delete(chanSource.addrs, n)

	_, err = FetchStaticChanBackups(chanSource)
	if err == nil {
		t.Fatalf("query with incomplete information should fail")
	}

	// To wrap up, we'll ensure that if we're unable to query the channel
	// source at all, then we'll fail as well.
	chanSource = newMockChannelSource()
	chanSource.failQuery = true
	_, err = FetchStaticChanBackups(chanSource)
	if err == nil {
		t.Fatalf("query should fail")
	}
}
