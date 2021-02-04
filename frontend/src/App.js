import React from 'react';
import { Mosaic, MosaicWindow, updateTree, getLeaves, Corner, getPathToCorner, getNodeAtPath, getOtherDirection } from 'react-mosaic-component';

import dropRight from 'lodash/dropRight';
import 'react-mosaic-component/react-mosaic-component.css';
import '@blueprintjs/core/lib/css/blueprint.css';
import '@blueprintjs/icons/lib/css/blueprint-icons.css';
import io from 'socket.io-client';
import './App.css';

const proto = require('./protos/hangouts_pb');

const getConvName = (conv) => {
  return conv.name ? conv.name
    : conv.users.filter(user => !user.is_self)
      .map(user => conv.users.length > 2 ? user.first_name : user.full_name)
      .join(", ")
}

class ConversationList extends React.Component {
  constructor(props) {
    super(props);
    this.state = {
      filter: '',
    }
  }

  render() {
    const { conversations, onClick } = this.props;

    return (
      <div className="ConversationList">
        <input onChange={(e) => {
          this.setState({ filter: e.target.value })
        }}></input>
        {conversations.filter(conv => !this.state.filter || getConvName(conv).toLowerCase().includes(this.state.filter)).map(conv => <div key={conv.id}>
          <button onClick={() => onClick(conv.id)}>
            {getConvName(conv)}
          </button>
        </div>)}
      </div>
    );
  }
}

class App extends React.Component {
  constructor(props) {
    super(props)
    this.state = {
      conversationsById: [],
      currentNode: null,
    };
  }

  getChatWindow(id, path) {
    if (this.state.conversationsById[id].events.length < 10) {
      this.loadConvEvents(id);
    }
    return (<MosaicWindow
      path={path}
      title={getConvName(this.state.conversationsById[id])}>
      <div>
        {this.state.conversationsById[id].events.length
        ? this.state.conversationsById[id].events.map(event => event.getChatMessage().getMessageContent().getSegmentList().map(seg => seg.getText()).join("\n")).join('\n')
        : 'Loading messages...'}
      </div>
      <input onKeyDown={(e) => {
        if (e.key === 'Enter') {
          this.socket.emit('conv_message', { id: id, message: e.target.value })
          console.log(e.target.value)
        }
      }}></input>
    </MosaicWindow>)
  }


  addToTopRight = (id) => {
    let { currentNode } = this.state;
    if (currentNode) {
      const path = getPathToCorner(currentNode, Corner.TOP_RIGHT);
      const parent = getNodeAtPath(currentNode, dropRight(path));
      const destination = getNodeAtPath(currentNode, path);
      const direction = parent ? getOtherDirection(parent.direction) : 'row';

      let first;
      let second;
      if (direction === 'row') {
        first = destination;
        second = id;
      } else {
        first = id;
        second = destination;
      }

      currentNode = updateTree(currentNode, [
        {
          path,
          spec: {
            $set: {
              direction,
              first,
              second,
            },
          },
        },
      ]);
    } else {
      currentNode = id;
    }

    this.setState({ currentNode });
  };


  render() {
    return (
      <React.StrictMode>
        <div className="App">
          <ConversationList
            conversations={Object.values(this.state.conversationsById).sort((a, b) => {
              return b.last_modified - a.last_modified
            })}
            onClick={(id) => {
              if (!getLeaves(this.state.currentNode).includes(id)) {
                this.addToTopRight(id)
              }
            }} />
          <Mosaic
            renderTile={(id, path) =>
              this.getChatWindow(id, path)
            }
            onChange={this.onChange}
            value={this.state.currentNode}
          />
        </div>
      </React.StrictMode>
    );
  }

  onChange = (currentNode) => {
    this.setState({ currentNode });
  };

  componentDidMount() {
    this.socket = io(`http://localhost:8000`);
    this.socket.on('chat_message', (chatEvent) => {
      const event = proto.Event.deserializeBinary(chatEvent);
      const id = event.getConversationId().getId();
      this.setState((state, props) => {
        const ret = {
          conversationsById: {
            ...state.conversationsById,
            [id]: {
              ...state.conversationsById[id],
              events: [...state.conversationsById[id].events, event.toObject()],
            }
          }
        }
        console.log(ret);
        console.log(ret.conversationsById[id])
        return ret;
      })
    })
    this.getDataFromDb();
  }

  loadConvEvents(id) {
    fetch(`http://localhost:8000/api/conversations/${id}`)
      .then((data) => {
        return data.arrayBuffer()
      })
      .then((res) => {
        const x = new Uint8Array(res);
        console.log(Buffer.from(x).toString('hex'));
        const cstate = proto.ConversationState.deserializeBinary(new Uint8Array(res));
        this.setState((state, props) => {
          console.log("cstate", cstate.toObject());
          const ret = {
            conversationsById: {
              ...state.conversationsById,
              [id]: {
                ...state.conversationsById[id],
                events: [...state.conversationsById[id].events, ...cstate.getEventList()],
              }
            }
          }
          console.log("after: ", ret.conversationsById[id].events[0].toObject())
          return ret
        })
      })
      .catch(console.log);
  }

  getDataFromDb = () => {
    fetch('http://localhost:8000/api/conversations')
      .then((data) => data.json())
      .then((res) => {
        console.log(res);
        this.setState({ conversationsById: res.reduce((acc, cur) => Object.assign(acc, { [cur.id]: { ...cur, events: [] } }), {}) });
      })
      .catch(err => console.log);
  };
}

export default App;